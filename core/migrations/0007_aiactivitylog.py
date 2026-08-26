from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_testsuiteaireviewjob"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIActivityLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "action_type",
                    models.CharField(
                        choices=[
                            ("REVIEW_TEST_CASE", "Review Test Case"),
                            ("REVIEW_TEST_SUITE", "Review Test Suite"),
                            ("ANALYZE_TEST_SUITE", "Analyze Test Suite"),
                        ],
                        max_length=64,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("SUCCESS", "Success"), ("FAILED", "Failed"), ("RUNNING", "Running")],
                        default="SUCCESS",
                        max_length=32,
                    ),
                ),
                ("message", models.TextField(blank=True, null=True)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "initiated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_activity_logs",
                        to="core.user",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_activity_logs",
                        to="core.project",
                    ),
                ),
                (
                    "test_case",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_activity_logs",
                        to="core.testcase",
                    ),
                ),
                (
                    "test_suite",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_activity_logs",
                        to="core.testsuite",
                    ),
                ),
            ],
            options={"db_table": "ai_activity_logs", "ordering": ("-started_at", "-id")},
        ),
    ]
