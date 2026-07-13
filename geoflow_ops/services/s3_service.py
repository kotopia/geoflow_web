# geoflow_ops/services/s3_service.py
"""
S3 Private Bucket + Presigned URL 기반 파일 업로드/다운로드 서비스

인증 방식:
- 로컬 개발: .env의 IAM User credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- 운영 배포: EC2 Instance Profile (환경변수 제거, boto3가 자동으로 임시 credentials 획득)

암호화:
- SSE-S3: AWS_KMS_KEY_ID 미설정 시 기본 (AES256)
- SSE-KMS: AWS_KMS_KEY_ID 설정 시 (KMS Key Policy에 Principal 추가 필요)
  * 로컬: arn:aws:iam::account-id:user/webgis-admin
  * 운영: arn:aws:iam::account-id:role/GeoFlowEC2InstanceRole
"""
import os
import uuid
from datetime import datetime, timezone as dt_timezone
from typing import Literal, Optional

import boto3
from botocore.client import Config
from django.conf import settings


def get_s3_client():
    """
    .env 기반 S3 클라이언트 생성
    - 로컬: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY 사용
    - 운영: EC2 Instance Profile 자동 사용 (환경변수 제거)
    """
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "ap-northeast-2"),
        config=Config(signature_version="s3v4"),
    )


def get_bucket_name() -> str:
    """업로드 대상 S3 버킷 이름 (.env에서 AWS_S3_BUCKET)"""
    bucket = os.environ.get("AWS_S3_BUCKET")
    if not bucket:
        raise ValueError("AWS_S3_BUCKET not set in environment")
    return bucket


def get_sse_config() -> dict:
    """
    서버측 암호화 설정
    
    - AWS_KMS_KEY_ID가 있으면 SSE-KMS 사용
      * 로컬 개발: KMS Key Policy에 IAM User(webgis-admin) ARN 추가 필요
      * 운영 배포: KMS Key Policy에 EC2 Instance Role ARN 추가 필요
      * 예: arn:aws:kms:ap-northeast-2:123456789012:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    
    - AWS_KMS_KEY_ID가 없으면 SSE-S3 사용 (AES256, 추가 권한 불필요)
    """
    kms_key_id = os.environ.get("AWS_KMS_KEY_ID")
    if kms_key_id:
        return {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": kms_key_id,
        }
    return {"ServerSideEncryption": "AES256"}


def build_object_key(
    tenant_db_alias: str,
    entity_type: Literal["employee", "contract", "orgunit", "event"],
    entity_id: str,
    purpose: str,
    extension: str,
    event_id: Optional[str] = None,
) -> str:
    """
    object_key 규칙:
    - 직원사진: tenants/<tenant_db_alias>/employees/<employee_id>/photo/<yyyy>/<mm>/<uuid>.<ext>
    - 계약첨부: tenants/<tenant_db_alias>/contracts/<contract_id>/attachments/<yyyy>/<mm>/<uuid>.<ext>
    - 회사파일: tenants/<tenant_db_alias>/orgunits/<orgunit_id>/<purpose>/<yyyy>/<mm>/<uuid>.<ext>
    - 이벤트: tenants/<tenant_db_alias>/events/<event_id>/<purpose>/<yyyy>/<mm>/<uuid>.<ext>
    """
    now = datetime.now(dt_timezone.utc)
    yyyy = now.strftime("%Y")
    mm = now.strftime("%m")
    unique_id = uuid.uuid4().hex

    if entity_type == "employee":
        path = f"tenants/{tenant_db_alias}/employees/{entity_id}/{purpose}/{yyyy}/{mm}/{unique_id}.{extension}"
    elif entity_type == "contract":
        path = f"tenants/{tenant_db_alias}/contracts/{entity_id}/{purpose}/{yyyy}/{mm}/{unique_id}.{extension}"
    elif entity_type == "orgunit":
        path = f"tenants/{tenant_db_alias}/orgunits/{entity_id}/{purpose}/{yyyy}/{mm}/{unique_id}.{extension}"
    elif entity_type == "event":
        # event 타입은 event_id를 경로에 사용
        if not event_id:
            raise ValueError("event_id is required for entity_type='event'")
        path = f"tenants/{tenant_db_alias}/events/{event_id}/{purpose}/{yyyy}/{mm}/{unique_id}.{extension}"
    else:
        raise ValueError(f"Unsupported entity_type: {entity_type}")

    return path


def generate_presigned_put_url(
    object_key: str,
    mime_type: Optional[str] = None,
    expires_in: int = 3600,
) -> dict:
    """
    Presigned PUT URL 생성 (클라이언트가 S3에 직접 업로드)
    
    Returns:
        {
            "presigned_url": str,
            "headers": {
                "Content-Type": str,
                "x-amz-server-side-encryption": str,  # or ...
            }
        }
    """
    s3_client = get_s3_client()
    bucket = get_bucket_name()
    sse = get_sse_config()

    params = {
        "Bucket": bucket,
        "Key": object_key,
    }
    if mime_type:
        params["ContentType"] = mime_type
    params.update(sse)

    url = s3_client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
    )

    # 클라이언트가 PUT 요청 시 함께 보낼 헤더
    headers = {}
    if mime_type:
        headers["Content-Type"] = mime_type
    if "ServerSideEncryption" in sse:
        headers["x-amz-server-side-encryption"] = sse["ServerSideEncryption"]
    if "SSEKMSKeyId" in sse:
        headers["x-amz-server-side-encryption-aws-kms-key-id"] = sse["SSEKMSKeyId"]

    return {
        "presigned_url": url,
        "headers": headers,
    }


def generate_presigned_get_url(
    object_key: str,
    expires_in: int = 3600,
    content_type: Optional[str] = None,
    disposition: Optional[str] = None,
    filename: Optional[str] = None,
) -> str:
    """
    Presigned GET URL 생성 (Private 버킷에서 다운로드/미리보기)
    
    Args:
        object_key: S3 객체 키
        expires_in: URL 유효 시간 (초)
        content_type: MIME 타입
        disposition: "inline" (미리보기) 또는 "attachment" (다운로드)
        filename: 다운로드 시 사용할 파일명
    
    Returns:
        Presigned GET URL
    """
    s3_client = get_s3_client()
    bucket = get_bucket_name()

    params = {
        "Bucket": bucket,
        "Key": object_key,
    }

    # Content-Type 설정
    if content_type:
        params["ResponseContentType"] = content_type

    # Content-Disposition 설정 (inline 또는 attachment)
    if disposition:
        if disposition == "inline":
            params["ResponseContentDisposition"] = "inline"
        elif disposition == "attachment" and filename:
            # RFC 5987 형식: attachment; filename*=UTF-8''encoded-filename
            from urllib.parse import quote
            encoded_filename = quote(filename)
            params["ResponseContentDisposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
        elif disposition == "attachment":
            params["ResponseContentDisposition"] = "attachment"

    url = s3_client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    return url


def extract_extension(filename: str) -> str:
    """파일명에서 확장자 추출 (소문자, 점 제거)"""
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return "bin"
