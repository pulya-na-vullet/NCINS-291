from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_testruntestcase_comment_author"),
    ]

    operations = [
        migrations.CreateModel(
            name="TraceabilityAIReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("response", models.TextField()),
                ("reviewed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="traceability_ai_review",
                        to="core.project",
                    ),
                ),
            ],
            options={
                "db_table": "traceability_ai_reviews",
                "ordering": ("-reviewed_at",),
            },
        ),
    ]
