from datetime import timedelta
from html import escape
import re
import logging
from urllib.parse import urljoin

import requests
from django.db import transaction
from django.db import OperationalError
from django.db.models import Prefetch
from django.utils import timezone

from .models import (
    AIAnalysis,
    AIProviderSettings,
    Comment,
    Project,
    ProjectIntegrationSettings,
    TestCase,
    TestCaseReview,
    TestCaseUserStory,
    TestRun,
    TestRunTestCase,
    TestSuite,
    TestStep,
    TraceabilityMatrix,
    TraceabilityAIReview,
    User,
    UserStory,
)

logger = logging.getLogger(__name__)


def build_api_response(success: bool, message: str = "", **payload):
    body = {"success": success}
    if message:
        body["message"] = message
    body.update(payload)
    return body


@transaction.atomic
def generate_and_store_matrix(project_id: int) -> TraceabilityMatrix:
    user_stories = UserStory.objects.filter(section__project_id=project_id).order_by("id")
    test_cases = TestCase.objects.filter(test_suite__project_id=project_id).order_by("id")
    review_scores = {
        row["test_case_id"]: row["overall_score"]
        for row in TestCaseReview.objects.filter(test_case_id__in=test_cases.values_list("id", flat=True)).values(
            "test_case_id",
            "overall_score",
        )
    }
    links = set(
        TestCaseUserStory.objects.filter(
            test_case_id__in=test_cases.values_list("id", flat=True),
            user_story_id__in=user_stories.values_list("id", flat=True),
        ).values_list("test_case_id", "user_story_id")
    )

    html = ["<table class=\"traceability-table\">"]
    html.append("<thead><tr><th class=\"user-story-header\">User Story \\ Test Case</th>")
    for tc in test_cases:
        tc_link = f"/test-suite/{tc.test_suite_id}?testCaseId={tc.id}"
        score = review_scores.get(tc.id)
        if score is None:
            score_badge = '<div class="tc-ai-score-badge no-score">AI: —</div>'
        elif score <= 4:
            score_badge = f'<div class="tc-ai-score-badge low-score">AI: {score}/10</div>'
        elif score <= 7:
            score_badge = f'<div class="tc-ai-score-badge medium-score">AI: {score}/10</div>'
        else:
            score_badge = f'<div class="tc-ai-score-badge high-score">AI: {score}/10</div>'
        html.append(
            f"<th class=\"test-case-header\">{score_badge}<a href=\"{tc_link}\" class=\"rotated-link\" "
            f"data-test-case-id=\"{tc.id}\" data-bs-toggle=\"popover\">TC-{tc.id}</a></th>"
        )
    html.append("</tr></thead><tbody>")
    for us in user_stories:
        us_name = escape(us.name or "", quote=True)
        criticality = us.business_criticality
        us_label = f"US {us.id}"
        if criticality is None:
            us_cell_class = "user-story-cell"
            criticality_badge = ""
        elif criticality <= 4:
            us_cell_class = "user-story-cell criticality-low"
            criticality_badge = f"<span class=\"badge bg-success ms-2\">{criticality}</span>"
        elif criticality <= 7:
            us_cell_class = "user-story-cell criticality-medium"
            criticality_badge = f"<span class=\"badge bg-warning text-dark ms-2\">{criticality}</span>"
        else:
            us_cell_class = "user-story-cell criticality-high"
            criticality_badge = f"<span class=\"badge bg-danger ms-2\">{criticality}</span>"
        html.append(
            f"<tr class=\"user-story-row\"><td class=\"{us_cell_class}\" title=\"{us_name}\">"
            f"<strong>{us_label}</strong>{criticality_badge}<br>{us_name}</td>"
        )
        for tc in test_cases:
            if (tc.id, us.id) in links:
                html.append("<td class=\"linked-cell\">✓</td>")
            else:
                html.append("<td class=\"unlinked-cell\"></td>")
        html.append("</tr>")
    html.append("</tbody></table>")

    matrix, _ = TraceabilityMatrix.objects.update_or_create(
        project_id=project_id,
        defaults={"matrix_html": "".join(html), "created_at": timezone.now()},
    )
    return matrix


def calculate_traceability_metrics(project_id: int):
    user_stories = list(UserStory.objects.filter(section__project_id=project_id).only("id", "business_criticality"))
    test_case_ids = list(TestCase.objects.filter(test_suite__project_id=project_id).values_list("id", flat=True))
    user_story_ids = [us.id for us in user_stories]
    linked_pairs = list(
        TestCaseUserStory.objects.filter(
            test_case_id__in=test_case_ids,
            user_story_id__in=user_story_ids,
        ).values_list("test_case_id", "user_story_id")
    )
    linked_user_story_ids = {pair[1] for pair in linked_pairs}
    linked_test_case_ids = {pair[0] for pair in linked_pairs}

    total_us = len(user_stories)
    covered_us = sum(1 for us in user_stories if us.id in linked_user_story_ids)
    uncovered_us = total_us - covered_us
    coverage_percent = round((covered_us * 100.0) / total_us, 2) if total_us else 0.0

    low_stories = [us for us in user_stories if us.business_criticality is not None and 1 <= us.business_criticality <= 4]
    medium_stories = [us for us in user_stories if us.business_criticality is not None and 5 <= us.business_criticality <= 7]
    high_stories = [us for us in user_stories if us.business_criticality is not None and 8 <= us.business_criticality <= 10]

    low_count = len(low_stories)
    medium_count = len(medium_stories)
    high_count = len(high_stories)

    low_covered = sum(1 for us in low_stories if us.id in linked_user_story_ids)
    medium_covered = sum(1 for us in medium_stories if us.id in linked_user_story_ids)
    high_covered = sum(1 for us in high_stories if us.id in linked_user_story_ids)

    orphan_test_cases_count = len(set(test_case_ids) - linked_test_case_ids)

    return {
        "coverage": {
            "total_us": total_us,
            "covered_us": covered_us,
            "uncovered_us": uncovered_us,
            "coverage_percent": coverage_percent,
        },
        "criticality": {
            "low_count": low_count,
            "medium_count": medium_count,
            "high_count": high_count,
            "total_us": total_us,
        },
        "criticality_coverage": {
            "high_covered": high_covered,
            "high_uncovered": high_count - high_covered,
            "medium_covered": medium_covered,
            "medium_uncovered": medium_count - medium_covered,
            "low_covered": low_covered,
            "low_uncovered": low_count - low_covered,
        },
        "orphan_test_cases": {
            "count": orphan_test_cases_count,
        },
    }


def bulk_refresh_matrices():
    for project_id in Project.objects.values_list("id", flat=True):
        try:
            generate_and_store_matrix(project_id)
        except OperationalError as exc:
            if "database is locked" in str(exc).lower():
                logger.warning(
                    "Skipped matrix refresh for project_id=%s: sqlite database is locked",
                    project_id,
                )
                continue
            raise


def ensure_default_admin():
    if not User.objects.filter(username="admin").exists():
        User.objects.create(
            username="admin",
            password="admin",
            full_name="Administrator",
            email=None,
            roles=[User.Role.ADMIN],
            enabled=True,
        )


def run_ai_test_suite_analysis(test_suite_id: int):
    test_cases = TestCase.objects.filter(test_suite_id=test_suite_id).order_by("id")
    ai_settings = _get_enabled_yandex_settings()
    summary = None
    if ai_settings:
        prompt = _build_test_suite_analysis_prompt(test_suite_id, list(test_cases))
        summary, _ = _request_yandex_completion(ai_settings, prompt, max_tokens=1200)
    if not summary:
        summary = f"Auto analysis: found {test_cases.count()} test cases in suite {test_suite_id}."
    analysis = AIAnalysis.objects.create(
        test_suite_id=test_suite_id,
        prompt="System-generated analysis prompt",
        ai_response=summary,
    )
    return build_api_response(True, "AI analysis completed", analysis_id=analysis.id, response=summary)


def create_or_update_review(test_case_id: int):
    test_case = TestCase.objects.filter(id=test_case_id).first()
    if not test_case:
        return None
    ai_settings = _get_enabled_yandex_settings()
    if ai_settings:
        result, error_message = _request_yandex_completion(
            ai_settings,
            _build_test_case_review_prompt(test_case),
            max_tokens=1200,
        )
        if not result:
            result = (
                "AI провайдер включен, но не удалось получить ответ. "
                f"{error_message or 'Проверьте настройки подключения.'}"
            )
        score = _extract_review_score(result)
        if score is None:
            score = _fallback_review_score(test_case)
    else:
        result = f"Auto review for test case {test_case_id}: name length={len(test_case.name or '')}"
        score = _fallback_review_score(test_case)
    review, _ = TestCaseReview.objects.update_or_create(
        test_case_id=test_case_id,
        defaults={"review_result": result, "overall_score": score},
    )
    return review


def create_test_run(project_id, payload):
    test_run = TestRun.objects.create(
        project_id=project_id,
        title=payload.get("title") or "New test run",
        description=payload.get("description"),
        executor_name=payload.get("executorName") or "unknown",
        creator_name=payload.get("creatorName") or "unknown",
    )
    test_case_ids = payload.get("testCaseIds") or []
    test_suite_ids = payload.get("testSuiteIds") or []
    if test_suite_ids:
        suite_case_ids = list(
            TestCase.objects.filter(test_suite_id__in=test_suite_ids).values_list("id", flat=True)
        )
        test_case_ids = list(set(test_case_ids + suite_case_ids))
    for tc in TestCase.objects.filter(id__in=test_case_ids):
        TestRunTestCase.objects.get_or_create(test_run=test_run, test_case=tc)
    return test_run


def normalize_status(value: str, allowed: list[str], default: str):
    if not value:
        return default
    normalized = value.strip().upper().replace(" ", "_")
    return normalized if normalized in allowed else default


def analyze_traceability_model_quality(project_id: int, force_refresh: bool = False):
    project = Project.objects.filter(id=project_id).first()
    if not project:
        return build_api_response(False, "Проект не найден")
    existing_review = TraceabilityAIReview.objects.filter(project_id=project_id).first()
    if existing_review and not force_refresh:
        return build_api_response(
            True,
            "Показан сохраненный результат AI-оценки",
            response=existing_review.response,
            reviewed_at=existing_review.reviewed_at,
            cached=True,
        )
    if not existing_review and not force_refresh:
        return build_api_response(False, "Сохраненная AI-оценка не найдена. Нажмите «Перезапросить».")

    user_stories = list(
        UserStory.objects.filter(section__project_id=project_id)
        .select_related("section")
        .order_by("section_id", "id")
    )
    test_cases = list(
        TestCase.objects.filter(test_suite__project_id=project_id)
        .prefetch_related("steps")
        .order_by("id")
    )
    test_case_map = {tc.id: tc for tc in test_cases}

    links = TestCaseUserStory.objects.filter(
        user_story_id__in=[us.id for us in user_stories],
        test_case_id__in=[tc.id for tc in test_cases],
    ).values("user_story_id", "test_case_id")
    us_to_tc_ids: dict[int, list[int]] = {}
    for link in links:
        us_to_tc_ids.setdefault(link["user_story_id"], []).append(link["test_case_id"])

    ai_settings = _get_enabled_yandex_settings()
    if ai_settings:
        response_text, error_message = _run_traceability_quality_in_batches(
            ai_settings,
            project,
            user_stories,
            us_to_tc_ids,
            test_case_map,
        )
        if not response_text:
            return build_api_response(
                False,
                error_message or "Не удалось получить ответ от AI для оценки тестовой модели",
            )
        review, _ = TraceabilityAIReview.objects.update_or_create(
            project_id=project_id,
            defaults={"response": response_text, "reviewed_at": timezone.now()},
        )
        return build_api_response(
            True,
            "AI оценка качества модели сформирована",
            response=review.response,
            reviewed_at=review.reviewed_at,
            cached=False,
        )

    fallback = _build_traceability_quality_fallback(user_stories, us_to_tc_ids, test_case_map)
    review, _ = TraceabilityAIReview.objects.update_or_create(
        project_id=project_id,
        defaults={"response": fallback, "reviewed_at": timezone.now()},
    )
    return build_api_response(
        True,
        "AI провайдер не включен, показана локальная эвристическая оценка",
        response=review.response,
        reviewed_at=review.reviewed_at,
        cached=False,
    )


def test_ai_provider_connection():
    settings = AIProviderSettings.objects.filter(provider=AIProviderSettings.Provider.YANDEX_GPT).first()
    if not settings:
        return build_api_response(False, "Настройки YandexGPT не найдены")
    if not settings.api_key or not settings.folder_id:
        return build_api_response(False, "Заполните API Key и Folder ID")
    response_text, error_message = _request_yandex_completion(
        settings,
        "Ответь ровно одной строкой: OK",
        max_tokens=20,
    )
    if not response_text:
        return build_api_response(False, error_message or "Нет ответа от AI провайдера")
    return build_api_response(True, "Подключение к YandexGPT успешно", response=response_text.strip())


def _get_enabled_yandex_settings():
    settings = AIProviderSettings.objects.filter(provider=AIProviderSettings.Provider.YANDEX_GPT, enabled=True).first()
    if not settings:
        return None
    if not settings.api_key or not settings.folder_id:
        return None
    return settings


def _request_yandex_completion(settings: AIProviderSettings, prompt: str, max_tokens: int = 1000) -> tuple[str | None, str | None]:
    model_name = (settings.model or "yandexgpt").strip()
    endpoint_url = (settings.endpoint_url or "").strip() or "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    model_uri_candidates = [f"gpt://{settings.folder_id}/{model_name}"]
    if "/" not in model_name:
        model_uri_candidates.append(f"gpt://{settings.folder_id}/{model_name}/latest")

    last_error = None
    for model_uri in model_uri_candidates:
        payload = {
            "modelUri": model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.2,
                "maxTokens": str(max_tokens),
            },
            "messages": [
                {"role": "system", "text": "Ты эксперт по тестированию ПО. Отвечай на русском языке."},
                {"role": "user", "text": prompt},
            ],
        }
        try:
            response = requests.post(
                endpoint_url,
                headers={
                    "Authorization": f"Api-Key {settings.api_key}",
                    "x-folder-id": settings.folder_id,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            if response.status_code >= 400:
                body_preview = (response.text or "")[:500]
                last_error = (
                    f"Ошибка AI провайдера ({response.status_code}) для modelUri={model_uri}. "
                    f"Ответ: {body_preview or 'пустой ответ'}"
                )
                continue
            data = response.json()
        except requests.RequestException as exc:
            last_error = f"Ошибка сети при запросе к AI провайдеру: {exc}"
            continue
        except ValueError:
            last_error = "AI провайдер вернул некорректный JSON"
            continue

        text = _extract_yandex_text(data)
        if text:
            return text, None
        last_error = (
            f"AI провайдер вернул ответ без текста для modelUri={model_uri}. "
            f"Проверьте model/folder/endpoint."
        )

    return None, last_error


def _extract_yandex_text(data: dict) -> str | None:
    try:
        text = (data.get("result") or {}).get("alternatives", [{}])[0].get("message", {}).get("text")
        if text:
            return text.strip()
    except (AttributeError, IndexError, TypeError):
        pass
    try:
        text = (data.get("result") or {}).get("alternatives", [{}])[0].get("text")
        if text:
            return text.strip()
    except (AttributeError, IndexError, TypeError):
        pass
    return None


def _build_test_case_review_prompt(test_case: TestCase) -> str:
    steps = list(test_case.steps.all().order_by("step_number"))
    steps_text = "\n".join(
        [
            f"{idx + 1}. Действие: {step.action or '-'}; Ожидаемый результат: {step.expected_result or '-'}"
            for idx, step in enumerate(steps)
        ]
    ) or "Шаги не указаны."
    return (
        "Выполни ревью тест-кейса. Дай краткий структурированный ответ:\n"
        "- Сильные стороны\n"
        "- Проблемы\n"
        "- Что улучшить\n"
        "- Итоговая оценка по шкале 1-10\n\n"
        f"Название: {test_case.name or '-'}\n"
        f"Описание: {test_case.description or '-'}\n"
        f"Предусловия: {test_case.preconditions or '-'}\n"
        f"Приоритет: {test_case.priority or '-'}\n"
        f"Шаги:\n{steps_text}"
    )


def _build_test_suite_analysis_prompt(test_suite_id: int, test_cases: list[TestCase]) -> str:
    lines = []
    for case in test_cases[:50]:
        lines.append(f"TC-{case.id}: {case.name or '-'} | priority={case.priority or '-'} | status={case.status or '-'}")
    cases_text = "\n".join(lines) or "Тест-кейсов нет."
    return (
        f"Проанализируй тест-сьют #{test_suite_id}. "
        "Дай краткий вывод о полноте покрытия, рисках и приоритетах доработки.\n\n"
        f"Список тест-кейсов:\n{cases_text}"
    )


def _build_traceability_quality_prompt(
    project: Project,
    user_stories: list[UserStory],
    us_to_tc_ids: dict[int, list[int]],
    test_case_map: dict[int, TestCase],
    compact_mode: bool = False,
) -> str:
    def clip(text: str | None, limit: int) -> str:
        value = (text or "").strip()
        if len(value) <= limit:
            return value or "-"
        return value[: max(limit - 1, 1)] + "…"

    def has_negative_signs(tc: TestCase) -> bool:
        source = f"{tc.name or ''} {tc.description or ''}".lower()
        markers = ("негатив", "ошибк", "invalid", "невер", "отказ", "fail", "forbidden", "denied")
        return any(marker in source for marker in markers)

    us_limit = 60 if compact_mode else 120
    tc_per_us_limit = 2 if compact_mode else 4
    steps_per_tc_limit = 1 if compact_mode else 3
    max_prompt_chars = 14000 if compact_mode else 28000

    header = (
        f"Оцени качество тестовой модели проекта '{project.name}'.\n\n"
        "Для каждой User Story:\n"
        "1) оцени полноту покрытия тестами;\n"
        "2) оцени качество тестов (ясность шагов, ожидаемые результаты);\n"
        "3) отметь наличие/отсутствие негативных проверок;\n"
        "4) дай оценку 1-10 по каждой US.\n\n"
        "В конце дай итоговую оценку всей модели 1-10 и 5 приоритетных улучшений.\n"
        "Отвечай на русском языке, структурированно и практично.\n\n"
        "Данные по US и ТК:\n"
    )

    blocks: list[str] = []
    chars_used = len(header)
    truncated = False
    for us in user_stories[:us_limit]:
        linked_tc_ids = us_to_tc_ids.get(us.id, [])
        if not linked_tc_ids:
            tc_block = "Нет связанных тест-кейсов."
        else:
            tc_lines = []
            for tc_id in linked_tc_ids[:tc_per_us_limit]:
                tc = test_case_map.get(tc_id)
                if not tc:
                    continue
                steps = list(tc.steps.all())[:steps_per_tc_limit]
                steps_text = "; ".join(
                    [f"{idx + 1}) {clip(step.action, 70)} -> {clip(step.expected_result, 70)}" for idx, step in enumerate(steps)]
                ) or "шаги не описаны"
                tc_lines.append(
                    f"- TC-{tc.id}: {clip(tc.name, 90)} | p={tc.priority or '-'} | s={tc.status or '-'} | "
                    f"neg={'да' if has_negative_signs(tc) else 'нет'} | steps={steps_text}"
                )
            tc_block = "\n".join(tc_lines) if tc_lines else "Нет связанных тест-кейсов."

        us_block = (
            f"\nUS-{us.id}: {clip(us.name, 140)}\n"
            f"Критичность: {us.business_criticality if us.business_criticality is not None else 'не задана'}\n"
            f"Покрывающие тесты:\n{tc_block}\n"
        )

        if chars_used + len(us_block) > max_prompt_chars:
            truncated = True
            break
        blocks.append(us_block)
        chars_used += len(us_block)

    suffix = ""
    if truncated or len(user_stories) > us_limit:
        suffix = (
            "\n\nПримечание: данные частично сокращены для соблюдения лимита контекста модели. "
            "Сфокусируйся на выявлении системных рисков и пробелов покрытия."
        )

    return header + "".join(blocks) + suffix


def _run_traceability_quality_in_batches(
    settings: AIProviderSettings,
    project: Project,
    user_stories: list[UserStory],
    us_to_tc_ids: dict[int, list[int]],
    test_case_map: dict[int, TestCase],
) -> tuple[str | None, str | None]:
    if not user_stories:
        return "В проекте нет User Story для анализа.", None

    batch_size = 25
    batch_results: list[str] = []
    total_batches = (len(user_stories) + batch_size - 1) // batch_size

    for idx, batch in enumerate(_chunked(user_stories, batch_size), start=1):
        prompt = _build_traceability_quality_prompt(
            project,
            batch,
            us_to_tc_ids,
            test_case_map,
            compact_mode=False,
        )
        batch_text, error_message = _request_yandex_completion(settings, prompt, max_tokens=1800)
        if not batch_text and _is_input_token_overflow_error(error_message):
            compact_prompt = _build_traceability_quality_prompt(
                project,
                batch,
                us_to_tc_ids,
                test_case_map,
                compact_mode=True,
            )
            batch_text, error_message = _request_yandex_completion(settings, compact_prompt, max_tokens=1800)

        if not batch_text:
            return (
                None,
                f"{error_message or 'Не удалось обработать батч'} (батч {idx}/{total_batches})",
            )

        batch_results.append(f"### Батч {idx}/{total_batches}\n{batch_text.strip()}")

    synthesis_prompt = _build_traceability_quality_synthesis_prompt(project, batch_results)
    synthesis_text, synthesis_error = _request_yandex_completion(settings, synthesis_prompt, max_tokens=1200)
    if not synthesis_text and _is_input_token_overflow_error(synthesis_error):
        compact_synthesis_prompt = _build_traceability_quality_synthesis_prompt(
            project,
            batch_results,
            compact_mode=True,
        )
        synthesis_text, synthesis_error = _request_yandex_completion(settings, compact_synthesis_prompt, max_tokens=1200)

    if not synthesis_text:
        synthesis_text = (
            "Итоговая сводка не получена автоматически. Ниже приведены результаты по всем батчам."
        )

    full_report = (
        f"Проект: {project.name}\n"
        f"User Story проанализировано: {len(user_stories)}\n"
        f"Батчей: {total_batches}\n\n"
        f"## Итоговая сводка\n{synthesis_text.strip()}\n\n"
        f"## Детальные результаты по батчам\n\n"
        f"{chr(10).join(batch_results)}"
    )
    return full_report, None


def _build_traceability_quality_synthesis_prompt(
    project: Project,
    batch_results: list[str],
    compact_mode: bool = False,
) -> str:
    max_chars_per_batch = 1200 if compact_mode else 2200
    blocks = []
    total_chars = 0
    total_limit = 14000 if compact_mode else 24000
    for idx, result in enumerate(batch_results, start=1):
        text = result.strip()
        if len(text) > max_chars_per_batch:
            text = text[: max_chars_per_batch - 1] + "…"
        block = f"Батч {idx}:\n{text}\n"
        if total_chars + len(block) > total_limit:
            blocks.append("... (часть батчей сокращена в сводном промпте)")
            break
        blocks.append(block)
        total_chars += len(block)

    return (
        f"Ниже результаты батч-анализа качества тестовой модели проекта '{project.name}'.\n"
        "Сформируй итоговую сводку:\n"
        "1) общая оценка модели 1-10;\n"
        "2) главные риски покрытия;\n"
        "3) топ-10 приоритетных улучшений;\n"
        "4) краткий вывод по негативным проверкам.\n"
        "Пиши на русском, структурированно.\n\n"
        f"{chr(10).join(blocks)}"
    )


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _is_input_token_overflow_error(error_message: str | None) -> bool:
    if not error_message:
        return False
    lower = error_message.lower()
    return "number of input tokens" in lower or "input tokens must be no more than" in lower


def _build_traceability_quality_fallback(
    user_stories: list[UserStory],
    us_to_tc_ids: dict[int, list[int]],
    test_case_map: dict[int, TestCase],
) -> str:
    lines = ["Локальная оценка (без внешнего AI):", ""]
    per_scores = []
    for us in user_stories:
        linked_ids = us_to_tc_ids.get(us.id, [])
        if not linked_ids:
            score = 1
            lines.append(f"US-{us.id}: {us.name} -> 1/10 (нет покрывающих ТК)")
            per_scores.append(score)
            continue
        has_steps = 0
        has_preconditions = 0
        has_negative_signs = 0
        for tc_id in linked_ids:
            tc = test_case_map.get(tc_id)
            if not tc:
                continue
            if tc.steps.exists():
                has_steps += 1
            if tc.preconditions:
                has_preconditions += 1
            text = f"{tc.name or ''} {tc.description or ''}".lower()
            if any(marker in text for marker in ["негатив", "ошибк", "invalid", "невер", "отказ", "fail"]):
                has_negative_signs += 1
        total = max(len(linked_ids), 1)
        score = 3
        score += round((has_steps / total) * 3)
        score += round((has_preconditions / total) * 2)
        score += round((has_negative_signs / total) * 2)
        score = min(max(score, 1), 10)
        per_scores.append(score)
        neg_note = "есть признаки негативных проверок" if has_negative_signs else "негативных проверок не обнаружено"
        lines.append(f"US-{us.id}: {us.name} -> {score}/10; {neg_note}")
    overall = round(sum(per_scores) / len(per_scores), 1) if per_scores else 0.0
    lines.append("")
    lines.append(f"Итоговая оценка модели: {overall}/10")
    lines.append("Рекомендация: включите AI провайдер для более точной экспертной оценки.")
    return "\n".join(lines)


def _extract_review_score(review_text: str | None) -> int | None:
    if not review_text:
        return None

    # Normalize common markdown/noise artifacts and unicode dashes.
    normalized = review_text
    normalized = normalized.replace(",", ".")
    normalized = normalized.replace("*", " ")
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    candidate_lines = []
    for raw_line in review_text.splitlines():
        line = raw_line.replace("*", " ")
        line = re.sub(r"[‐‑‒–—−]", "-", line)
        compact = re.sub(r"\s+", " ", line).strip()
        if compact:
            candidate_lines.append(compact)

    # First pass: line-based detection for "Итоговая/Общая оценка".
    for line in candidate_lines:
        lower = line.lower()
        if "итоговая оценка" not in lower and "общая оценка" not in lower and "оценка по шкале" not in lower:
            continue
        numbers = re.findall(r"\d+(?:\.\d+)?", line)
        # Often line contains "1-10" and then final score, e.g. "Итоговая ... 1-10: 6"
        if not numbers:
            continue
        parsed = []
        for token in numbers:
            try:
                parsed.append(float(token))
            except ValueError:
                continue
        if not parsed:
            continue
        # Prefer the last value in score-like lines.
        candidate = parsed[-1]
        if 0 < candidate <= 10:
            return int(round(candidate))

    # Second pass: explicit patterns.
    patterns = [
        r"(?:итоговая|общая)\s+оценка[^\n\r]{0,80}?[:=]\s*(\d+(?:\.\d+)?)",
        r"оценка\s+по\s+шкале\s*1\s*-\s*10[^\n\r]{0,40}?[:=]\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*/\s*10",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if 0 < value <= 10:
            return int(round(value))
    return None


def _fallback_review_score(test_case: TestCase) -> int:
    score = 1
    if test_case.description:
        score += 3
    if test_case.preconditions:
        score += 2
    if test_case.steps.exists():
        score += 3
    if test_case.priority in {TestCase.Priority.HIGH, TestCase.Priority.CRITICAL}:
        score += 1
    return min(score, 10)


def import_test_cases_from_provider(test_suite_id: int, provider: str):
    suite = TestSuite.objects.select_related("project").filter(id=test_suite_id).first()
    if not suite:
        return build_api_response(False, "Тест-сьют не найден")

    settings = ProjectIntegrationSettings.objects.filter(project_id=suite.project_id).first()
    if not settings:
        return build_api_response(False, "Для проекта не настроены интеграции. Откройте админку.")

    provider_key = (provider or "").strip().lower()
    if provider_key == "allure":
        rows, error = _fetch_from_allure(settings)
    elif provider_key == "testit":
        rows, error = _fetch_from_testit(settings)
    else:
        return build_api_response(False, "Неизвестный провайдер импорта. Доступно: allure, testit")

    if error:
        return build_api_response(False, error)
    if not rows:
        return build_api_response(False, "Не удалось найти тест-кейсы у выбранного провайдера")

    created = 0
    skipped = 0
    imported_case_ids = []
    existing_names = set(
        TestCase.objects.filter(test_suite_id=test_suite_id).values_list("name", flat=True)
    )
    next_index = TestCase.objects.filter(test_suite_id=test_suite_id).count() + 1

    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            name = f"Imported {provider_key.upper()} TC #{next_index}"
            next_index += 1
        if name in existing_names:
            skipped += 1
            continue

        case = TestCase.objects.create(
            test_suite_id=test_suite_id,
            name=name[:255],
            description=row.get("description"),
            preconditions=row.get("preconditions"),
            priority=TestCase.Priority.MEDIUM,
            status=TestCase.Status.DRAFT,
        )
        existing_names.add(name)
        created += 1
        imported_case_ids.append(case.id)

        step_rows = row.get("steps") or []
        if isinstance(step_rows, list):
            step_objects = []
            for idx, step in enumerate(step_rows, start=1):
                if isinstance(step, dict):
                    action = (step.get("action") or step.get("name") or "").strip()
                    expected = (
                        step.get("expected_result")
                        or step.get("expectedResult")
                        or step.get("expected")
                        or step.get("result")
                    )
                else:
                    action = str(step).strip()
                    expected = None
                if not action:
                    continue
                step_objects.append(
                    TestStep(
                        test_case=case,
                        step_number=idx,
                        action=action,
                        expected_result=expected,
                    )
                )
            if step_objects:
                TestStep.objects.bulk_create(step_objects, batch_size=200)

    return build_api_response(
        True,
        f"Импорт завершен: создано {created}, пропущено {skipped}",
        provider=provider_key,
        created_count=created,
        skipped_count=skipped,
        imported_case_ids=imported_case_ids,
    )


def _fetch_from_allure(settings: ProjectIntegrationSettings):
    if not settings.allure_base_url or not settings.allure_api_token or not settings.allure_project_id:
        return [], "Для Allure TestOps заполните base URL, project id и API token в админке."

    base_url = settings.allure_base_url.rstrip("/") + "/"
    project_id = settings.allure_project_id.strip()
    token = settings.allure_api_token.strip()
    candidate_paths = [
        f"api/rs/testcase?projectId={project_id}&size=500&page=0",
        f"api/rs/testcase?projectId={project_id}",
        f"api/rs/test-cases?projectId={project_id}&size=500&page=0",
    ]
    last_error = None
    for path in candidate_paths:
        url = urljoin(base_url, path)
        headers_list = [
            {"Authorization": f"Api-Token {token}", "Accept": "application/json"},
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
            {"X-Api-Token": token, "Accept": "application/json"},
        ]
        for headers in headers_list:
            try:
                response = requests.get(url, headers=headers, timeout=45)
            except requests.RequestException as exc:
                last_error = f"Ошибка подключения к Allure TestOps: {exc}"
                continue
            if response.status_code >= 400:
                last_error = (
                    f"Allure вернул HTTP {response.status_code} для {url}. "
                    f"Проверьте URL/токен/доступы."
                )
                continue
            try:
                payload = response.json()
            except ValueError:
                last_error = "Allure вернул не-JSON ответ."
                continue
            rows = _extract_allure_cases(payload)
            if rows:
                return rows, None
    return [], (last_error or "Не удалось получить тест-кейсы из Allure TestOps.")


def _extract_allure_cases(payload):
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("content") or payload.get("items") or payload.get("results") or payload.get("data") or []
    else:
        items = []
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        steps_raw = item.get("steps") or item.get("testSteps") or item.get("scenario") or []
        normalized.append(
            {
                "name": item.get("name") or item.get("title"),
                "description": item.get("description") or item.get("descriptionHtml"),
                "preconditions": item.get("precondition") or item.get("preconditions"),
                "steps": _normalize_steps(steps_raw),
            }
        )
    return normalized


def _fetch_from_testit(settings: ProjectIntegrationSettings):
    if not settings.testit_base_url or not settings.testit_private_token or not settings.testit_project_id:
        return [], "Для TestIT заполните base URL, project id и private token в админке."

    base_url = settings.testit_base_url.rstrip("/") + "/"
    project_id = settings.testit_project_id.strip()
    token = settings.testit_private_token.strip()
    candidate_paths = [
        f"api/v2/testCases?projectId={project_id}",
        f"api/v2/test-cases?projectId={project_id}",
    ]
    last_error = None
    for path in candidate_paths:
        url = urljoin(base_url, path)
        headers_list = [
            {"PrivateToken": token, "Accept": "application/json"},
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        ]
        for headers in headers_list:
            try:
                response = requests.get(url, headers=headers, timeout=45)
            except requests.RequestException as exc:
                last_error = f"Ошибка подключения к TestIT: {exc}"
                continue
            if response.status_code >= 400:
                last_error = (
                    f"TestIT вернул HTTP {response.status_code} для {url}. "
                    f"Проверьте URL/токен/доступы."
                )
                continue
            try:
                payload = response.json()
            except ValueError:
                last_error = "TestIT вернул не-JSON ответ."
                continue
            rows = _extract_testit_cases(payload)
            if rows:
                return rows, None
    return [], (last_error or "Не удалось получить тест-кейсы из TestIT.")


def _extract_testit_cases(payload):
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items") or payload.get("content") or payload.get("results") or payload.get("data") or []
    else:
        items = []
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        steps_raw = item.get("steps") or item.get("testSteps") or item.get("stepResults") or []
        normalized.append(
            {
                "name": item.get("name") or item.get("title"),
                "description": item.get("description"),
                "preconditions": item.get("preconditions"),
                "steps": _normalize_steps(steps_raw),
            }
        )
    return normalized


def _normalize_steps(steps_raw):
    if not isinstance(steps_raw, list):
        return []
    normalized = []
    for step in steps_raw:
        if isinstance(step, dict):
            normalized.append(
                {
                    "action": step.get("action") or step.get("title") or step.get("name") or step.get("description"),
                    "expected_result": (
                        step.get("expected_result")
                        or step.get("expectedResult")
                        or step.get("expected")
                        or step.get("result")
                    ),
                }
            )
        else:
            normalized.append({"action": str(step), "expected_result": None})
    return normalized
