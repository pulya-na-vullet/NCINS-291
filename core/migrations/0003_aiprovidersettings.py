import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_userstory_business_criticality"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIProviderSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("provider", models.CharField(choices=[("YANDEX_GPT", "Yandex Gpt")], max_length=32, unique=True)),
                ("enabled", models.BooleanField(default=False)),
                ("api_key", models.TextField(blank=True, null=True)),
                ("folder_id", models.CharField(blank=True, max_length=255, null=True)),
                ("model", models.CharField(default="yandexgpt", max_length=128)),
                ("endpoint_url", models.CharField(default="https://llm.api.cloud.yandex.net/foundationModels/v1/completion", max_length=255)),
                ("token_refresh_interval_ms", models.BigIntegerField(default=36000000)),
            ],
            options={
                "db_table": "ai_provider_settings",
                "ordering": ("provider",),
            },
        ),
    ]

