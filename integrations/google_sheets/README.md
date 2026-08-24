# GeoFlow Google Sheets contract sync

Temporary Google Sheets client for the read-only contract API.

## Target sheet

The bound spreadsheet should contain the tab `GeoFlow_계약정보`. The script will create it if missing and writes these columns in order:

계약ID, 레거시ID, 계약번호, 계약명, 프로젝트ID, 프로젝트코드, 프로젝트명, 전체프로젝트코드, 착수일, 준공일, 계약금액, 상태, 계약유형, 구분, 발주처ID, 발주처, 하도급처ID, 하도급처, 조직ID, 조직, 비고, 확장정보(JSON), 생성일시, 수정일시, 프로젝트전체(JSON)

## Security model

- API URL: `https://geoflow.co.kr/api/temp/contracts/`
- Authentication: `X-GeoFlow-Temp-Key` request header
- The API key is stored only in Apps Script `Script Properties`.
- Do not put the API key in a spreadsheet cell, formula, repository file, or URL query string.
- The GeoFlow endpoint remains tenant-pinned and read-only.
- The temporary endpoint can later be removed without database migrations.

## Apps Script

Use `contract_sync.gs` as the bound Apps Script for the `계약관리_GeoFlow` spreadsheet.

The script adds a `GeoFlow` menu with:

- 계약정보 새로고침
- API 키 설정
- 1시간 자동 새로고침 설치
- 자동 새로고침 해제

The sync replaces only data rows under the header in `GeoFlow_계약정보`; it does not overwrite the existing manual `시트1` table.

## Activation boundary

The server endpoint is intentionally disabled by default. Production activation requires a separately reviewed operation that sets the target tenant group and temporary API key and restarts the GeoFlow service. Do not perform that operation as part of ordinary repository or UI work.
