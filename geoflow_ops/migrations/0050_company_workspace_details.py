"""Add document detail fields and company selectors without rewriting existing evidence."""
from django.db import migrations, models
import django.db.models.deletion
from uuid import uuid4


def seed_references(apps, schema_editor):
    if schema_editor.connection.alias == 'default':
        return
    groups = [
        ('company.legal_form','기업형태',['법인사업자','개인사업자','공공기관','비영리법인']),
        ('company.enterprise_size','기업규모',['소기업','중기업','중견기업','대기업']),
        ('company.credit_agency','평가기관',[]),
        ('company.rating_type','평가종류',['기업신용평가','공공기관 제출용','민간기업 제출용']),
        ('company.document_name','증명·평가 명칭',[]),
    ]
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT id FROM ops.settings_nodes WHERE system_key='company.references'")
        found = cursor.fetchone()
        root = found[0] if found else uuid4()
        if not found:
            cursor.execute('''INSERT INTO ops.settings_nodes
                (id,code,name,node_type,ord,active,system_key,locked)
                VALUES (%s,'company-references','기업정보','group',90,true,'company.references',true)''',[root])
        for ref,label,values in groups:
            cursor.execute('SELECT id FROM ops.settings_nodes WHERE field_ref=%s',[ref])
            if cursor.fetchone():
                continue  # Never overwrite an existing tenant catalogue.
            category = uuid4()
            cursor.execute('''INSERT INTO ops.settings_nodes
                (id,parent_id,code,name,node_type,ord,active,system_key,locked,field_ref)
                VALUES (%s,%s,%s,%s,'category',10,true,%s,true,%s)''',[category,root,ref,label,ref,ref])
            for order,name in enumerate(values):
                cursor.execute('''INSERT INTO ops.settings_nodes
                    (id,parent_id,code,name,node_type,ord,active,locked)
                    VALUES (%s,%s,%s,%s,'value',%s,true,false)''',[uuid4(),category,'company-'+uuid4().hex,name,order*10])


class Migration(migrations.Migration):
    dependencies = [('webgisapp','0049_company_overview')]
    operations = [
        migrations.AlterField(model_name='companyprofile',name='node_kind',field=models.CharField(max_length=20,choices=[('company','본점'),('branch','지점')],default='company')),
        migrations.AlterField(model_name='companyregistration',name='kind',field=models.CharField('구분',max_length=20,choices=[('registration','업등록'),('report','신고'),('certification','인증·확인')])),
        migrations.AddField(model_name='companyregistration',name='issued_on',field=models.DateField('발급일',null=True,blank=True)),
        migrations.AddField(model_name='companyregistration',name='valid_from',field=models.DateField('유효기간 시작일',null=True,blank=True)),
        migrations.AddField(model_name='companyregistration',name='items',field=models.JSONField('확인 대상 품목',default=list,blank=True)),
        migrations.AddField(model_name='companycredit',name='previous',field=models.ForeignKey('webgisapp.companycredit',null=True,blank=True,on_delete=django.db.models.deletion.PROTECT)),
        migrations.AddConstraint(model_name='companycredit',constraint=models.UniqueConstraint(fields=['previous'],condition=models.Q(previous__isnull=False),name='company_credit_successor')),
        migrations.RunPython(seed_references,migrations.RunPython.noop),
    ]
