from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_aiactivitylog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectIntegrationSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("jira_bug_create_url", models.TextField(blank=True, null=True)),
                ("allure_base_url", models.CharField(blank=True, max_length=500, null=True)),
                ("allure_project_id", models.CharField(blank=True, max_length=128, null=True)),
                ("allure_api_token", models.TextField(blank=True, null=True)),
                ("testit_base_url", models.CharField(blank=True, max_length=500, null=True)),
                ("testit_project_id", models.CharField(blank=True, max_length=128, null=True)),
                ("testit_private_token", models.TextField(blank=True, null=True)),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="integration_settings",
                        to="core.project",
                    ),
                ),
            ],
            options={
                "db_table": "project_integration_settings",
                "ordering": ("project_id",),
            },
        ),
    ]
