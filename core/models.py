from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)


class Project(TimestampedModel):
    name = models.CharField(max_length=255)

    class Meta:
        db_table = "projects"
        ordering = ("id",)

    def __str__(self):
        return self.name


class ProjectIntegrationSettings(TimestampedModel):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="integration_settings",
    )
    jira_bug_create_url = models.TextField(blank=True, null=True)

    allure_base_url = models.CharField(max_length=500, blank=True, null=True)
    allure_project_id = models.CharField(max_length=128, blank=True, null=True)
    allure_api_token = models.TextField(blank=True, null=True)

    testit_base_url = models.CharField(max_length=500, blank=True, null=True)
    testit_project_id = models.CharField(max_length=128, blank=True, null=True)
    testit_private_token = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "project_integration_settings"
        ordering = ("project_id",)


class Section(TimestampedModel):
    name = models.CharField(max_length=255)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="sections",
    )

    class Meta:
        db_table = "sections"
        ordering = ("id",)


class UserStory(TimestampedModel):
    name = models.CharField(max_length=255)
    business_criticality = models.IntegerField(null=True, blank=True)
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="user_stories",
    )

    class Meta:
        db_table = "user_stories"
        ordering = ("id",)


class TestSuite(TimestampedModel):
    name = models.CharField(max_length=255)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="test_suites",
    )

    class Meta:
        db_table = "test_suites"
        ordering = ("id",)


class Tag(models.Model):
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#6c757d")
    created_at = models.DateTimeField(default=timezone.now)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tags",
    )

    class Meta:
        db_table = "tags"
        ordering = ("id",)


class TestCase(TimestampedModel):
    class Priority(models.TextChoices):
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"
        CRITICAL = "CRITICAL"

    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        REVIEW = "REVIEW"
        ACTIVE = "ACTIVE"
        ARCHIVE = "ARCHIVE"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    preconditions = models.TextField(blank=True, null=True)
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    test_suite = models.ForeignKey(
        TestSuite,
        on_delete=models.CASCADE,
        related_name="test_cases",
    )
    tags = models.ManyToManyField(
        Tag,
        through="TestCaseTag",
        related_name="test_cases",
        blank=True,
    )

    class Meta:
        db_table = "test_cases"
        ordering = ("id",)


class TestCaseTag(models.Model):
    test_case = models.ForeignKey(TestCase, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        db_table = "test_case_tags"
        unique_together = ("test_case", "tag")


class TestStep(TimestampedModel):
    step_number = models.IntegerField()
    action = models.TextField()
    expected_result = models.TextField(blank=True, null=True)
    test_case = models.ForeignKey(
        TestCase,
        on_delete=models.CASCADE,
        related_name="steps",
    )

    class Meta:
        db_table = "test_steps"
        ordering = ("step_number", "id")


class TestCaseUserStory(models.Model):
    test_case = models.ForeignKey(
        TestCase,
        on_delete=models.CASCADE,
        related_name="test_case_user_stories",
    )
    user_story = models.ForeignKey(
        UserStory,
        on_delete=models.CASCADE,
        related_name="test_case_user_stories",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="test_case_user_stories",
    )

    class Meta:
        db_table = "test_case_user_stories"
        unique_together = ("test_case", "user_story")


class User(models.Model):
    class Role(models.TextChoices):
        ADMIN = "ADMIN"
        ANALYST = "ANALYST"
        TESTER = "TESTER"

    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=255)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(null=True, blank=True, unique=True)
    roles = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    deactivation_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "users"
        ordering = ("id",)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    def has_role(self, role: str) -> bool:
        return role in (self.roles or [])


class Comment(models.Model):
    class CommentType(models.TextChoices):
        MANUAL = "MANUAL"
        AI_GENERATED = "AI_GENERATED"
        SYSTEM = "SYSTEM"

    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    test_case = models.ForeignKey(
        TestCase,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comments",
    )
    comment_type = models.CharField(
        max_length=32,
        choices=CommentType.choices,
        default=CommentType.MANUAL,
    )

    class Meta:
        db_table = "comments"
        ordering = ("id",)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)


class TestCaseReview(models.Model):
    test_case = models.OneToOneField(
        TestCase,
        on_delete=models.CASCADE,
        related_name="review",
    )
    review_result = models.TextField(blank=True, null=True)
    overall_score = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "test_case_reviews"
        ordering = ("id",)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)


class TestRun(TimestampedModel):
    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED"
        IN_PROGRESS = "IN_PROGRESS"
        COMPLETED = "COMPLETED"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    executor_name = models.CharField(max_length=255)
    creator_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NOT_STARTED,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="test_runs",
    )

    class Meta:
        db_table = "test_runs"
        ordering = ("-created_at",)


class TestRunTestCase(TimestampedModel):
    class TestCaseStatus(models.TextChoices):
        NOT_RUN = "NOT_RUN"
        PASSED = "PASSED"
        FAILED = "FAILED"
        SKIPPED = "SKIPPED"

    test_run = models.ForeignKey(
        TestRun,
        on_delete=models.CASCADE,
        related_name="test_run_test_cases",
    )
    test_case = models.ForeignKey(
        TestCase,
        on_delete=models.CASCADE,
        related_name="test_run_test_cases",
    )
    status = models.CharField(
        max_length=32,
        choices=TestCaseStatus.choices,
        default=TestCaseStatus.NOT_RUN,
    )
    comment = models.TextField(blank=True, null=True)
    comment_author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="test_run_case_comments",
    )
    comment_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "test_run_test_cases"
        unique_together = ("test_run", "test_case")
        ordering = ("id",)


class TraceabilityMatrix(models.Model):
    project_id = models.BigIntegerField(db_index=True)
    matrix_html = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "traceability_matrices"
        ordering = ("-created_at",)


class AIAnalysis(models.Model):
    test_suite = models.ForeignKey(
        TestSuite,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_analyses",
    )
    prompt = models.TextField(blank=True, null=True)
    ai_response = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ai_analysis"
        ordering = ("-created_at",)


class TraceabilityAIReview(TimestampedModel):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="traceability_ai_review",
    )
    response = models.TextField()
    reviewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "traceability_ai_reviews"
        ordering = ("-reviewed_at",)


class TestSuiteAIReviewJob(TimestampedModel):
    class Status(models.TextChoices):
        IDLE = "IDLE"
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    test_suite = models.OneToOneField(
        TestSuite,
        on_delete=models.CASCADE,
        related_name="ai_review_job",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.IDLE)
    queue_case_ids = models.JSONField(default=list)
    total_cases = models.IntegerField(default=0)
    processed_cases = models.IntegerField(default=0)
    success_cases = models.IntegerField(default=0)
    failed_cases = models.IntegerField(default=0)
    started_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="started_ai_review_jobs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "test_suite_ai_review_jobs"
        ordering = ("-updated_at",)


class AIActivityLog(TimestampedModel):
    class ActionType(models.TextChoices):
        REVIEW_TEST_CASE = "REVIEW_TEST_CASE"
        REVIEW_TEST_SUITE = "REVIEW_TEST_SUITE"
        ANALYZE_TEST_SUITE = "ANALYZE_TEST_SUITE"
        ANALYZE_TRACEABILITY_MODEL = "ANALYZE_TRACEABILITY_MODEL"

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"
        RUNNING = "RUNNING"

    action_type = models.CharField(max_length=64, choices=ActionType.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUCCESS)
    message = models.TextField(blank=True, null=True)
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_activity_logs",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_activity_logs",
    )
    test_suite = models.ForeignKey(
        TestSuite,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_activity_logs",
    )
    test_case = models.ForeignKey(
        TestCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_activity_logs",
    )
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_activity_logs"
        ordering = ("-started_at", "-id")


class AIProviderSettings(TimestampedModel):
    class Provider(models.TextChoices):
        YANDEX_GPT = "YANDEX_GPT"

    provider = models.CharField(max_length=32, choices=Provider.choices, unique=True)
    enabled = models.BooleanField(default=False)
    api_key = models.TextField(blank=True, null=True)
    folder_id = models.CharField(max_length=255, blank=True, null=True)
    model = models.CharField(max_length=128, default="yandexgpt")
    endpoint_url = models.CharField(
        max_length=255,
        default="https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
    )
    token_refresh_interval_ms = models.BigIntegerField(default=36000000)

    class Meta:
        db_table = "ai_provider_settings"
        ordering = ("provider",)

# Create your models here.
