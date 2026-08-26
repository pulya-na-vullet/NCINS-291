from rest_framework import serializers

from .models import (
    Comment,
    Project,
    Section,
    Tag,
    TestCase,
    TestCaseReview,
    TestCaseUserStory,
    TestRun,
    TestRunTestCase,
    TestStep,
    TestSuite,
    TraceabilityMatrix,
    User,
    UserStory,
)


class TagSerializer(serializers.ModelSerializer):
    projectId = serializers.IntegerField(source="project_id", read_only=True)

    class Meta:
        model = Tag
        fields = ("id", "name", "color", "created_at", "projectId")


class TestStepSerializer(serializers.ModelSerializer):
    testCaseId = serializers.IntegerField(source="test_case_id", read_only=True)

    class Meta:
        model = TestStep
        fields = ("id", "step_number", "action", "expected_result", "created_at", "updated_at", "testCaseId")


class UserStorySerializer(serializers.ModelSerializer):
    sectionId = serializers.IntegerField(source="section_id", read_only=True)

    class Meta:
        model = UserStory
        fields = ("id", "name", "business_criticality", "created_at", "updated_at", "sectionId")


class CommentSerializer(serializers.ModelSerializer):
    userName = serializers.CharField(source="user.username", read_only=True)
    userUsername = serializers.CharField(source="user.username", read_only=True)
    userFullName = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Comment
        fields = (
            "id",
            "content",
            "created_at",
            "updated_at",
            "test_case_id",
            "user_id",
            "userName",
            "userUsername",
            "userFullName",
            "comment_type",
        )


class TestCaseSerializer(serializers.ModelSerializer):
    testSuiteId = serializers.IntegerField(source="test_suite_id", read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    steps = TestStepSerializer(many=True, read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    userStories = serializers.SerializerMethodField()

    class Meta:
        model = TestCase
        fields = (
            "id",
            "name",
            "description",
            "preconditions",
            "priority",
            "status",
            "created_at",
            "updated_at",
            "testSuiteId",
            "tags",
            "steps",
            "comments",
            "userStories",
        )

    def get_userStories(self, obj):
        links = TestCaseUserStory.objects.filter(test_case=obj).select_related("user_story")
        return UserStorySerializer([ln.user_story for ln in links], many=True).data


class TestSuiteSerializer(serializers.ModelSerializer):
    projectId = serializers.IntegerField(source="project_id", read_only=True)

    class Meta:
        model = TestSuite
        fields = ("id", "name", "created_at", "updated_at", "projectId")


class SectionSerializer(serializers.ModelSerializer):
    projectId = serializers.IntegerField(source="project_id", read_only=True)

    class Meta:
        model = Section
        fields = ("id", "name", "created_at", "updated_at", "projectId")


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ("id", "name", "created_at", "updated_at")


class UserSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name")
    deactivationReason = serializers.CharField(source="deactivation_reason", required=False, allow_null=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "password",
            "fullName",
            "email",
            "roles",
            "enabled",
            "created_at",
            "updated_at",
            "deactivationReason",
        )
        extra_kwargs = {"password": {"write_only": True}}


class TestRunTestCaseSerializer(serializers.ModelSerializer):
    testCase = TestCaseSerializer(source="test_case", read_only=True)
    testRunId = serializers.IntegerField(source="test_run_id", read_only=True)
    commentAuthorId = serializers.IntegerField(source="comment_author_id", read_only=True)
    commentAuthorName = serializers.CharField(source="comment_author.full_name", read_only=True)
    commentAuthorUsername = serializers.CharField(source="comment_author.username", read_only=True)

    class Meta:
        model = TestRunTestCase
        fields = (
            "id",
            "testRunId",
            "testCase",
            "status",
            "comment",
            "comment_updated_at",
            "commentAuthorId",
            "commentAuthorName",
            "commentAuthorUsername",
            "created_at",
            "updated_at",
        )


class TestRunSerializer(serializers.ModelSerializer):
    projectId = serializers.IntegerField(source="project_id", read_only=True)
    testCases = TestRunTestCaseSerializer(many=True, read_only=True, source="test_run_test_cases")
    stats = serializers.SerializerMethodField()

    class Meta:
        model = TestRun
        fields = (
            "id",
            "title",
            "description",
            "executor_name",
            "creator_name",
            "status",
            "created_at",
            "updated_at",
            "projectId",
            "testCases",
            "stats",
        )

    def get_stats(self, obj):
        rows = obj.test_run_test_cases.all()
        total_count = rows.count()
        passed_count = rows.filter(status="PASSED").count()
        failed_count = rows.filter(status="FAILED").count()
        skipped_count = rows.filter(status="SKIPPED").count()
        not_run_count = rows.filter(status="NOT_RUN").count()
        def pct(v):
            return 0 if total_count == 0 else round((v * 100.0) / total_count, 2)
        return {
            "total_count": total_count,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "not_run_count": not_run_count,
            "passed_percentage": pct(passed_count),
            "failed_percentage": pct(failed_count),
            "skipped_percentage": pct(skipped_count),
            "not_run_percentage": pct(not_run_count),
        }


class TestCaseReviewSerializer(serializers.ModelSerializer):
    testCaseId = serializers.IntegerField(source="test_case_id", read_only=True)

    class Meta:
        model = TestCaseReview
        fields = ("id", "testCaseId", "review_result", "overall_score", "created_at", "updated_at")


class TraceabilityMatrixSerializer(serializers.ModelSerializer):
    class Meta:
        model = TraceabilityMatrix
        fields = ("id", "project_id", "matrix_html", "created_at")
