from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User as DjangoUser
from django.db import connection
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from functools import wraps

from .models import (
    AIActivityLog,
    AIProviderSettings,
    Project,
    ProjectIntegrationSettings,
    Section,
    TestRun,
    TestSuite,
    TraceabilityMatrix,
    User as CoreUser,
)
from .serializers import TestRunSerializer, TestSuiteSerializer
from .services import calculate_traceability_metrics, generate_and_store_matrix


ROLE_ADMIN = "ADMIN"
ROLE_ANALYST = "ANALYST"
ROLE_TESTER = "TESTER"
_DEMO_USERS_ENSURED = False


def _ai_settings_table_ready() -> bool:
    try:
        return "ai_provider_settings" in connection.introspection.table_names()
    except Exception:
        return False


def _default_home_for_role(role: str) -> str:
    if role == ROLE_ADMIN:
        return "/admin/users"
    if role == ROLE_TESTER:
        return "/project-qa"
    return "/projects"


def _resolve_user_role(request) -> str:
    if not request.user.is_authenticated:
        return ROLE_ANALYST
    core_user_any = CoreUser.objects.filter(username=request.user.username).first()
    if core_user_any and not core_user_any.enabled:
        return "DISABLED"
    core_user = CoreUser.objects.filter(username=request.user.username, enabled=True).first()
    roles = core_user.roles if core_user and core_user.roles else []
    if ROLE_ADMIN in roles:
        return ROLE_ADMIN
    if ROLE_TESTER in roles:
        return ROLE_TESTER
    if ROLE_ANALYST in roles:
        return ROLE_ANALYST
    # Fallback for legacy/demo usernames.
    if core_user_any and core_user_any.enabled is False:
        return "DISABLED"
    if request.user.username == "admin":
        return ROLE_ADMIN
    if request.user.username == "tester":
        return ROLE_TESTER
    return ROLE_ANALYST


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url="/login")
        def wrapped(request, *args, **kwargs):
            current_role = _resolve_user_role(request)
            if current_role == "DISABLED":
                auth_logout(request)
                messages.error(request, "Пользователь деактивирован. Вход запрещен.")
                return redirect("/login")
            if current_role in allowed_roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, "Недостаточно прав для доступа к разделу.")
            return redirect(_default_home_for_role(current_role))

        return wrapped

    return decorator


def _ensure_demo_auth_users():
    global _DEMO_USERS_ENSURED
    if _DEMO_USERS_ENSURED:
        return

    mapping = (
        ("admin", ROLE_ADMIN, "Администратор"),
        ("analyst", ROLE_ANALYST, "Аналитик"),
        ("tester", ROLE_TESTER, "Тестировщик"),
    )
    try:
        with transaction.atomic():
            for username, role, full_name in mapping:
                core_user, _ = CoreUser.objects.get_or_create(
                    username=username,
                    defaults={
                        "password": username,
                        "full_name": full_name,
                        "roles": [role],
                        "enabled": True,
                    },
                )

                user, created = DjangoUser.objects.get_or_create(
                    username=username,
                    defaults={"first_name": full_name, "is_active": bool(core_user.enabled)},
                )
                changed = False
                if created:
                    user.set_password(username)
                    changed = True
                if user.is_active != bool(core_user.enabled):
                    user.is_active = bool(core_user.enabled)
                    changed = True
                if not user.first_name:
                    user.first_name = full_name
                    changed = True
                if changed:
                    user.save()
    except OperationalError:
        # SQLite may be temporarily locked by another request/task.
        return

    _DEMO_USERS_ENSURED = True


@never_cache
@ensure_csrf_cookie
def login_page(request):
    _ensure_demo_auth_users()

    if request.user.is_authenticated:
        return redirect(_default_home_for_role(_resolve_user_role(request)))

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            core_user = CoreUser.objects.filter(username=username).first()
            if core_user and not core_user.enabled:
                return render(request, "login.html", {"login_error": True})
            auth_login(request, user)
            return redirect(_default_home_for_role(_resolve_user_role(request)))

        return render(request, "login.html", {"login_error": True})

    return render(request, "login.html", {"logged_out": request.GET.get("logout") == "1"})


@login_required(login_url="/login")
def logout_page(request):
    if request.method in {"POST", "GET"}:
        auth_logout(request)
    return redirect("/login?logout=1")


@role_required(ROLE_ADMIN, ROLE_ANALYST)
def projects_page(request):
    return render(request, "projects.html")


@role_required(ROLE_ADMIN, ROLE_ANALYST)
def project_detail_page(request, id):
    project = Project.objects.filter(id=id).first()
    if not project:
        return redirect("/")
    return render(request, "project-detail.html", {"project": project})


@role_required(ROLE_ADMIN, ROLE_ANALYST)
def section_detail_page(request, id):
    section = Section.objects.filter(id=id).first()
    if not section:
        return redirect("/")
    return render(
        request,
        "section-detail.html",
        {
            "section": section,
            "userRole": _resolve_user_role(request),
        },
    )


@role_required(ROLE_ADMIN, ROLE_TESTER)
def test_suite_detail_page(request, id):
    suite = TestSuite.objects.filter(id=id).first()
    if not suite:
        return redirect("/project-qa")
    core_user = CoreUser.objects.filter(username=request.user.username).first()
    integration = ProjectIntegrationSettings.objects.filter(project_id=suite.project_id).first()
    return render(
        request,
        "test-suite-detail.html",
        {
            "testSuite": TestSuiteSerializer(suite).data,
            "testSuiteCreatedAtDisplay": suite.created_at.strftime("%Y-%m-%d в %H:%M:%S"),
            "currentUserId": core_user.id if core_user else "",
            "currentUserRole": _resolve_user_role(request),
            "jiraBugCreateUrl": integration.jira_bug_create_url if integration else "",
        },
    )


@role_required(ROLE_ADMIN, ROLE_TESTER)
def project_qa_page(request):
    return render(request, "project-qa.html", {"projects": Project.objects.all()})


@role_required(ROLE_ADMIN, ROLE_TESTER)
def project_qa_detail_page(request, id):
    project = Project.objects.filter(id=id).first()
    if not project:
        return redirect("/project-qa")
    suites = TestSuite.objects.filter(project_id=id)
    return render(request, "project-qa-detail.html", {"project": project, "testSuites": TestSuiteSerializer(suites, many=True).data})


@role_required(ROLE_ADMIN, ROLE_TESTER)
def test_runs_page(request, project_id):
    project = Project.objects.filter(id=project_id).first()
    if not project:
        return redirect("/project-qa")
    test_runs = TestRunSerializer(TestRun.objects.filter(project_id=project_id), many=True).data
    return render(request, "test-runs.html", {"project": project, "testRuns": test_runs})


@role_required(ROLE_ADMIN, ROLE_TESTER)
def test_run_detail_page(request, id):
    test_run = TestRun.objects.filter(id=id).first()
    if not test_run:
        return redirect("/project-qa")
    core_user = CoreUser.objects.filter(username=request.user.username).first()
    return render(
        request,
        "test-run-detail.html",
        {
            "testRun": TestRunSerializer(test_run).data,
            "currentUserId": core_user.id if core_user else "",
            "currentUserRole": _resolve_user_role(request),
        },
    )


@role_required(ROLE_ADMIN, ROLE_ANALYST, ROLE_TESTER)
def traceability_matrix_page(request, project_id):
    project = Project.objects.filter(id=project_id).first()
    if not project:
        return redirect("/project-qa")
    force_refresh = request.GET.get("refresh") in {"1", "true", "yes"}
    matrix = TraceabilityMatrix.objects.filter(project_id=project_id).order_by("-created_at").first()
    try:
        needs_refresh = force_refresh or not matrix
        if matrix and matrix.matrix_html:
            # Rebuild legacy-heavy HTML once to reduce payload/parse time.
            if "data-bs-trigger=" in matrix.matrix_html:
                needs_refresh = True
        if needs_refresh:
            matrix = generate_and_store_matrix(project_id)
    except Exception:
        # Fallback to latest stored matrix if regeneration fails for any reason.
        matrix = matrix or TraceabilityMatrix.objects.filter(project_id=project_id).order_by("-created_at").first()
    matrix_html = matrix.matrix_html if matrix else ""
    user_role = _resolve_user_role(request)
    core_user = CoreUser.objects.filter(username=request.user.username).first()
    return render(
        request,
        "traceability-matrix.html",
        {
            "project": project,
            "matrixHtml": matrix_html,
            "userRole": user_role,
            "currentUserId": core_user.id if core_user else "",
            "matrixMetrics": calculate_traceability_metrics(project_id),
        },
    )


@role_required(ROLE_ADMIN)
def admin_users_page(request):
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        full_name = (request.POST.get("fullName") or "").strip()
        email = (request.POST.get("email") or "").strip() or None
        role = (request.POST.get("role") or "").strip()
        if not username or not password or not full_name or not role:
            messages.error(request, "Заполните обязательные поля пользователя.")
            return redirect("/admin/users")
        if CoreUser.objects.filter(username=username).exists():
            messages.error(request, "Пользователь с таким именем уже существует.")
            return redirect("/admin/users")

        core_user = CoreUser.objects.create(
            username=username,
            password=password,
            full_name=full_name,
            email=email,
            roles=[role],
            enabled=True,
        )
        django_user, created = DjangoUser.objects.get_or_create(
            username=username,
            defaults={"email": email or "", "first_name": full_name},
        )
        django_user.set_password(password)
        django_user.is_active = True
        django_user.save()
        messages.success(request, f"Пользователь {core_user.username} создан.")
        return redirect("/admin/users")

    users = CoreUser.objects.all()
    admin_count = sum(1 for user in users if "ADMIN" in (user.roles or []))
    yandex_settings = None
    ai_settings_table_ready = _ai_settings_table_ready()
    if ai_settings_table_ready:
        try:
            yandex_settings = AIProviderSettings.objects.filter(provider=AIProviderSettings.Provider.YANDEX_GPT).first()
        except (OperationalError, ProgrammingError):
            ai_settings_table_ready = False
    return render(
        request,
        "admin/users.html",
        {
            "users": users,
            "totalUsers": users.count(),
            "activeUsers": users.filter(enabled=True).count(),
            "adminUsers": admin_count,
            "roles": [choice for choice, _ in CoreUser.Role.choices],
            "yandexConfigured": bool(yandex_settings and yandex_settings.api_key and yandex_settings.folder_id),
            "yandexEnabled": bool(yandex_settings and yandex_settings.enabled),
            "aiSettingsTableReady": ai_settings_table_ready,
        },
    )


@role_required(ROLE_ADMIN)
def admin_ai_settings_page(request):
    if not _ai_settings_table_ready():
        messages.error(
            request,
            "Таблица настроек AI не создана. Выполните миграции: python manage.py migrate",
        )
        return redirect("/admin/users")

    settings_obj, _ = AIProviderSettings.objects.get_or_create(
        provider=AIProviderSettings.Provider.YANDEX_GPT,
        defaults={
            "model": "yandexgpt",
            "endpoint_url": "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            "token_refresh_interval_ms": 36000000,
        },
    )

    if request.method == "POST":
        enabled = request.POST.get("enabled") == "on"
        api_key = (request.POST.get("apiKey") or "").strip()
        folder_id = (request.POST.get("folderId") or "").strip()
        model = (request.POST.get("model") or "yandexgpt").strip()
        endpoint_url = (request.POST.get("endpointUrl") or settings_obj.endpoint_url).strip()
        token_refresh_raw = (request.POST.get("tokenRefreshIntervalMs") or "").strip()

        token_refresh_interval_ms = settings_obj.token_refresh_interval_ms
        if token_refresh_raw:
            try:
                token_refresh_interval_ms = int(token_refresh_raw)
            except ValueError:
                messages.error(request, "Интервал обновления токена должен быть целым числом (мс).")
                return redirect("/admin/ai-settings")

        # Allow enabling provider when credentials were previously saved and
        # user only toggles "enabled" without re-entering secrets.
        effective_api_key = api_key or (settings_obj.api_key or "").strip()
        effective_folder_id = folder_id or (settings_obj.folder_id or "").strip()
        if enabled and (not effective_api_key or not effective_folder_id):
            messages.error(request, "Для включения YandexGPT необходимо заполнить API Key и Folder ID.")
            return redirect("/admin/ai-settings")

        if api_key:
            settings_obj.api_key = api_key
        settings_obj.folder_id = folder_id or settings_obj.folder_id
        settings_obj.model = model or "yandexgpt"
        settings_obj.endpoint_url = endpoint_url or settings_obj.endpoint_url
        settings_obj.token_refresh_interval_ms = token_refresh_interval_ms
        settings_obj.enabled = enabled
        settings_obj.save()
        messages.success(request, "Настройки YandexGPT сохранены.")
        return redirect("/admin/ai-settings")

    masked_api_key = ""
    if settings_obj.api_key:
        if len(settings_obj.api_key) <= 8:
            masked_api_key = "*" * len(settings_obj.api_key)
        else:
            masked_api_key = f"{settings_obj.api_key[:4]}***{settings_obj.api_key[-4:]}"

    return render(
        request,
        "admin/ai-settings.html",
        {
            "providerSettings": settings_obj,
            "maskedApiKey": masked_api_key,
        },
    )


@role_required(ROLE_ADMIN)
def admin_ai_activity_page(request):
    logs = list(
        AIActivityLog.objects.select_related("initiated_by", "project", "test_suite", "test_case")
        .all()
        .order_by("-started_at", "-id")[:300]
    )
    return render(
        request,
        "admin/ai-activity.html",
        {
            "logs": logs,
            "totalLogs": len(logs),
            "successLogs": sum(1 for row in logs if row.status == AIActivityLog.Status.SUCCESS),
            "failedLogs": sum(1 for row in logs if row.status == AIActivityLog.Status.FAILED),
            "runningLogs": sum(1 for row in logs if row.status == AIActivityLog.Status.RUNNING),
        },
    )


@role_required(ROLE_ADMIN)
def admin_project_integrations_page(request):
    if request.method == "POST":
        project_id = request.POST.get("projectId")
        project = Project.objects.filter(id=project_id).first()
        if not project:
            messages.error(request, "Проект не найден.")
            return redirect("/admin/project-integrations")
        settings_obj, _ = ProjectIntegrationSettings.objects.get_or_create(project=project)
        settings_obj.jira_bug_create_url = (request.POST.get("jiraBugCreateUrl") or "").strip() or None
        settings_obj.allure_base_url = (request.POST.get("allureBaseUrl") or "").strip() or None
        settings_obj.allure_project_id = (request.POST.get("allureProjectId") or "").strip() or None
        settings_obj.allure_api_token = (request.POST.get("allureApiToken") or "").strip() or settings_obj.allure_api_token
        settings_obj.testit_base_url = (request.POST.get("testitBaseUrl") or "").strip() or None
        settings_obj.testit_project_id = (request.POST.get("testitProjectId") or "").strip() or None
        settings_obj.testit_private_token = (
            (request.POST.get("testitPrivateToken") or "").strip() or settings_obj.testit_private_token
        )
        settings_obj.save()
        messages.success(request, f"Интеграции для проекта «{project.name}» сохранены.")
        return redirect("/admin/project-integrations")

    projects = list(Project.objects.all().order_by("id"))
    settings_map = {
        row.project_id: row
        for row in ProjectIntegrationSettings.objects.filter(project_id__in=[p.id for p in projects])
    }
    project_rows = [{"project": project, "settings": settings_map.get(project.id)} for project in projects]
    return render(
        request,
        "admin/project-integrations.html",
        {
            "projectRows": project_rows,
        },
    )


@role_required(ROLE_ADMIN)
@require_POST
def admin_user_activate(request, id):
    user = get_object_or_404(CoreUser, id=id)
    user.enabled = True
    user.deactivation_reason = None
    user.save()
    django_user = DjangoUser.objects.filter(username=user.username).first()
    if django_user:
        django_user.is_active = True
        django_user.save()
    messages.success(request, f"Пользователь {user.username} активирован.")
    return redirect("/admin/users")


@role_required(ROLE_ADMIN)
@require_POST
def admin_user_deactivate(request, id):
    user = get_object_or_404(CoreUser, id=id)
    user.enabled = False
    user.deactivation_reason = "Деактивирован администратором"
    user.save()
    django_user = DjangoUser.objects.filter(username=user.username).first()
    if django_user:
        django_user.is_active = False
        django_user.save()
    messages.success(request, f"Пользователь {user.username} деактивирован.")
    return redirect("/admin/users")
