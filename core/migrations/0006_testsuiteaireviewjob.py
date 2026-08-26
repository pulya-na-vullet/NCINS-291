from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_traceabilityaireview"),
    ]

    operations = [
        migrations.CreateModel(
            name="TestSuiteAIReviewJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "status",
                    models.CharField(
                        choices=[("IDLE", "Idle"), ("RUNNING", "Running"), ("COMPLETED", "Completed"), ("FAILED", "Failed")],
                        default="IDLE",
                        max_length=32,
                    ),
                ),
                ("queue_case_ids", models.JSONField(default=list)),
                ("total_cases", models.IntegerField(default=0)),
                ("processed_cases", models.IntegerField(default=0)),
                ("success_cases", models.IntegerField(default=0)),
                ("failed_cases", models.IntegerField(default=0)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, null=True)),
                (
                    "started_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="started_ai_review_jobs",
                        to="core.user",
                    ),
                ),
                (
                    "test_suite",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_review_job",
                        to="core.testsuite",
                    ),
                ),
            ],
            options={"db_table": "test_suite_ai_review_jobs", "ordering": ("-updated_at",)},
        ),
    ]
