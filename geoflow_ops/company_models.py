"""Tenant-owned company profile facts; HR and attachments retain their owners."""
import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class CompanyProfile(models.Model):
    company = models.OneToOneField('MyOrgUnit', primary_key=True, on_delete=models.CASCADE)
    parent = models.ForeignKey('MyOrgUnit', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    node_kind = models.CharField(max_length=20, choices=[('company', '법인/기업'), ('branch', '지점')], default='company')
    is_primary = models.BooleanField(default=False)
    industry = models.CharField('업종', max_length=200, blank=True)
    business = models.TextField('사업내용', blank=True)
    founded_on = models.DateField('설립일', null=True, blank=True)
    legal_form = models.CharField('기업형태', max_length=100, blank=True)
    enterprise_size = models.CharField('기업규모', max_length=100, blank=True)
    homepage = models.URLField('홈페이지', blank=True)
    capital = models.DecimalField('자본금(원)', max_digits=20, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)])
    corporate_no = models.CharField('법인번호', max_length=30, blank=True)
    fax = models.CharField('팩스', max_length=50, blank=True)

    class Meta:
        app_label = 'webgisapp'
        db_table = '"ops"."company_profile"'
        constraints = [models.UniqueConstraint(fields=['is_primary'], condition=models.Q(is_primary=True), name='company_one_primary')]


class CompanyFact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey('MyOrgUnit', on_delete=models.CASCADE)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True
        app_label = 'webgisapp'


class CompanyRegistration(CompanyFact):
    kind = models.CharField('구분', max_length=20, choices=[('registration','업등록'),('report','신고'),('certification','인증')])
    name = models.CharField('명칭', max_length=200)
    number = models.CharField('등록/신고번호', max_length=100, blank=True)
    occurred_on = models.DateField('등록·신고일')
    issuer = models.CharField('발급기관', max_length=200, blank=True)
    status = models.CharField('상태', max_length=20, choices=[('active','유효'),('pending','진행중'),('cancelled','취소')], default='active')
    expires_on = models.DateField('만료일', null=True, blank=True)
    memo = models.TextField('비고', blank=True)
    previous = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT)
    event = models.OneToOneField('ProcessEvent', null=True, on_delete=models.PROTECT, editable=False)
    class Meta(CompanyFact.Meta):
        db_table = '"ops"."company_registration"'
        constraints = [models.UniqueConstraint(fields=['previous'], condition=models.Q(previous__isnull=False), name='company_registration_successor')]


class CompanyRevenue(CompanyFact):
    year = models.PositiveSmallIntegerField('회계연도', validators=[MinValueValidator(1900), MaxValueValidator(2200)])
    fiscal_on = models.DateField('결산 기준일')
    amount = models.DecimalField('매출액(원)', max_digits=20, decimal_places=0, validators=[MinValueValidator(0)])
    confirmed = models.BooleanField('확정', default=False)
    source = models.CharField('출처', max_length=200)
    class Meta(CompanyFact.Meta):
        db_table = '"ops"."company_revenue"'
        constraints = [models.UniqueConstraint(fields=['company','year'], name='company_revenue_year'), models.CheckConstraint(condition=models.Q(amount__gte=0), name='company_revenue_nonnegative')]


class CompanyHeadcount(CompanyFact):
    year = models.PositiveSmallIntegerField('연말 기준연도', validators=[MinValueValidator(1900), MaxValueValidator(2200)])
    count = models.PositiveIntegerField('연말 사원수')
    source = models.CharField('근거/출처', max_length=200)
    class Meta(CompanyFact.Meta):
        db_table = '"ops"."company_headcount"'
        constraints = [models.UniqueConstraint(fields=['company','year'], name='company_headcount_year')]


class CompanyCredit(CompanyFact):
    agency = models.CharField('평가기관', max_length=200)
    rating_type = models.CharField('평가종류', max_length=100)
    grade = models.CharField('신용등급', max_length=30)
    evaluated_on = models.DateField('평가일')
    expires_on = models.DateField('유효기간 종료일', null=True, blank=True)
    fiscal_on = models.DateField('재무 기준일', null=True, blank=True)
    representative = models.BooleanField('대표 신용등급으로 표시', default=False)
    event = models.OneToOneField('ProcessEvent', null=True, on_delete=models.PROTECT, editable=False)
    class Meta(CompanyFact.Meta):
        db_table = '"ops"."company_credit"'
        constraints = [models.UniqueConstraint(fields=['company'], condition=models.Q(representative=True), name='company_one_credit')]


class CompanyEvidence(CompanyFact):
    record_kind = models.CharField(max_length=20)
    record_id = models.UUIDField()
    attachment = models.ForeignKey('Attachment', on_delete=models.PROTECT)
    class Meta(CompanyFact.Meta):
        db_table = '"ops"."company_evidence"'
        constraints = [models.UniqueConstraint(fields=['record_kind','record_id','attachment'], name='company_evidence_unique')]
