from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("procurement", "0001_initial")]
    operations = [migrations.AddField(
        model_name="collectionjob", name="progress",
        field=models.JSONField(default=dict, blank=True),
    )]
