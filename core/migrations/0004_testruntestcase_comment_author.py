from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_aiprovidersettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="testruntestcase",
            name="comment_author",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="test_run_case_comments",
                to="core.user",
            ),
        ),
        migrations.AddField(
            model_name="testruntestcase",
            name="comment_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
