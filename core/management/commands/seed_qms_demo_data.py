import random

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Project, Section, TestCase, TestCaseUserStory, TestStep, TestSuite, UserStory


AIRCRAFT_PROJECT_NAME = "QMS Demo - Aircraft Manufacturing Program"
FLOWER_PROJECT_NAME = "QMS Demo - Flower Startup Platform"


class Command(BaseCommand):
    help = (
        "Seed large demo datasets for QMS testing: "
        "1) aircraft program (1100 US, 78% covered), "
        "2) flower startup (50 US, 700 TC)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=20260712, help="Random seed for deterministic generation.")
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="Do not remove existing demo projects with the same names before seeding.",
        )
        parser.add_argument("--aircraft-us", type=int, default=1100)
        parser.add_argument("--aircraft-tc", type=int, default=1600)
        parser.add_argument("--aircraft-coverage", type=float, default=0.78)
        parser.add_argument("--flower-us", type=int, default=50)
        parser.add_argument("--flower-tc", type=int, default=700)

    @transaction.atomic
    def handle(self, *args, **options):
        rnd = random.Random(options["seed"])

        if not options["keep_existing"]:
            deleted, _ = Project.objects.filter(name__in=[AIRCRAFT_PROJECT_NAME, FLOWER_PROJECT_NAME]).delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f"Removed existing demo rows: {deleted}"))

        aircraft = self._build_aircraft_project(
            rnd=rnd,
            us_count=options["aircraft_us"],
            tc_count=options["aircraft_tc"],
            coverage_ratio=options["aircraft_coverage"],
        )
        flower = self._build_flower_project(
            rnd=rnd,
            us_count=options["flower_us"],
            tc_count=options["flower_tc"],
        )

        self.stdout.write(self.style.SUCCESS("Demo dataset created successfully."))
        self.stdout.write(
            self.style.SUCCESS(
                (
                    f"- {AIRCRAFT_PROJECT_NAME}: US={aircraft['us_total']}, TC={aircraft['tc_total']}, "
                    f"covered US={aircraft['covered_us']} ({aircraft['coverage_percent']}%), "
                    f"uncovered US={aircraft['uncovered_us']}"
                )
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                (
                    f"- {FLOWER_PROJECT_NAME}: US={flower['us_total']}, TC={flower['tc_total']}, "
                    f"covered US={flower['covered_us']} ({flower['coverage_percent']}%), "
                    f"uncovered US={flower['uncovered_us']}"
                )
            )
        )

    def _build_aircraft_project(self, rnd: random.Random, us_count: int, tc_count: int, coverage_ratio: float):
        project = Project.objects.create(name=AIRCRAFT_PROJECT_NAME)
        sections = self._create_sections(
            project,
            [
                "Требования летной годности",
                "Проектирование и CAD",
                "Производство фюзеляжа",
                "Производство крыла",
                "Силовая установка",
                "Авионика и ПО",
                "Наземные испытания",
                "Летные испытания",
                "Безопасность и сертификация",
                "Логистика и поставщики",
            ],
        )

        us_objects = []
        for idx in range(1, us_count + 1):
            section = sections[(idx - 1) % len(sections)]
            criticality = rnd.randint(1, 10)
            us_objects.append(
                UserStory(
                    section=section,
                    name=f"US-AIR-{idx:04d}: Обеспечить контроль этапа {idx} для программы сборки самолёта",
                    business_criticality=criticality,
                )
            )
        UserStory.objects.bulk_create(us_objects, batch_size=1000)
        us_ids = list(UserStory.objects.filter(section__project=project).values_list("id", flat=True).order_by("id"))

        suites = self._create_suites(project, "Aircraft Suite", 24)
        tc_objects = []
        for idx in range(1, tc_count + 1):
            suite = suites[(idx - 1) % len(suites)]
            tc_objects.append(
                TestCase(
                    test_suite=suite,
                    name=f"TC-AIR-{idx:04d}: Проверка операции №{idx}",
                    description=(
                        f"Проверить корректность выполнения производственной или испытательной операции {idx} "
                        "в рамках программы самолётостроения."
                    ),
                    preconditions="Система в рабочем состоянии, оператор авторизован, данные партии загружены.",
                    priority=self._priority_from_index(idx),
                    status=TestCase.Status.ACTIVE,
                )
            )
        TestCase.objects.bulk_create(tc_objects, batch_size=1000)
        test_cases = list(TestCase.objects.filter(test_suite__project=project).order_by("id"))
        tc_ids = [tc.id for tc in test_cases]

        step_objects = []
        for tc in test_cases:
            step_objects.append(
                TestStep(
                    test_case=tc,
                    step_number=1,
                    action="Открыть экран операции и ввести параметры контроля.",
                    expected_result="Система принимает параметры без ошибок валидации.",
                )
            )
            step_objects.append(
                TestStep(
                    test_case=tc,
                    step_number=2,
                    action="Запустить выполнение операции и сформировать отчёт.",
                    expected_result="Операция завершается успешно, отчёт сохраняется в журнале.",
                )
            )
        TestStep.objects.bulk_create(step_objects, batch_size=1000)

        covered_us_target = max(0, min(us_count, int(round(us_count * coverage_ratio))))
        covered_us_ids = set(rnd.sample(us_ids, covered_us_target)) if covered_us_target else set()
        link_rows = []
        tc_cursor = 0
        for us_id in covered_us_ids:
            tc_id = tc_ids[tc_cursor % len(tc_ids)]
            tc_cursor += 1
            link_rows.append(
                TestCaseUserStory(test_case_id=tc_id, user_story_id=us_id, project_id=project.id)
            )

        extra_links = int(tc_count * 1.3)
        covered_us_ids_list = list(covered_us_ids)
        for _ in range(extra_links):
            if not covered_us_ids_list:
                break
            link_rows.append(
                TestCaseUserStory(
                    test_case_id=rnd.choice(tc_ids),
                    user_story_id=rnd.choice(covered_us_ids_list),
                    project_id=project.id,
                )
            )
        TestCaseUserStory.objects.bulk_create(link_rows, batch_size=2000, ignore_conflicts=True)

        actual_covered = (
            TestCaseUserStory.objects.filter(project_id=project.id).values("user_story_id").distinct().count()
        )
        return self._stats(us_total=us_count, tc_total=tc_count, covered_us=actual_covered)

    def _build_flower_project(self, rnd: random.Random, us_count: int, tc_count: int):
        project = Project.objects.create(name=FLOWER_PROJECT_NAME)
        sections = self._create_sections(
            project,
            [
                "Каталог и витрина",
                "Оформление заказа",
                "Оплата и возвраты",
                "Личный кабинет",
                "Админка и контент",
            ],
        )

        us_objects = []
        for idx in range(1, us_count + 1):
            section = sections[(idx - 1) % len(sections)]
            us_objects.append(
                UserStory(
                    section=section,
                    name=f"US-FLR-{idx:03d}: Улучшить пользовательский путь в цветочном сервисе ({idx})",
                    business_criticality=rnd.randint(1, 10),
                )
            )
        UserStory.objects.bulk_create(us_objects, batch_size=500)
        us_ids = list(UserStory.objects.filter(section__project=project).values_list("id", flat=True).order_by("id"))

        suites = self._create_suites(project, "Flower Suite", 14)
        tc_objects = []
        for idx in range(1, tc_count + 1):
            suite = suites[(idx - 1) % len(suites)]
            tc_objects.append(
                TestCase(
                    test_suite=suite,
                    name=f"TC-FLR-{idx:04d}: Сценарий заказа цветов #{idx}",
                    description="Проверка веб-сценария каталога, корзины, оформления и уведомлений.",
                    preconditions="Открыт сайт, доступны карточки товаров и активен API корзины.",
                    priority=self._priority_from_index(idx + 1),
                    status=TestCase.Status.ACTIVE,
                )
            )
        TestCase.objects.bulk_create(tc_objects, batch_size=1000)
        test_cases = list(TestCase.objects.filter(test_suite__project=project).order_by("id"))

        step_objects = []
        for tc in test_cases:
            step_objects.append(
                TestStep(
                    test_case=tc,
                    step_number=1,
                    action="Добавить букет в корзину и перейти к оформлению.",
                    expected_result="Товар отображается в корзине с корректной ценой.",
                )
            )
        TestStep.objects.bulk_create(step_objects, batch_size=1000)

        link_rows = []
        tc_ids = [tc.id for tc in test_cases]
        # Ensure every US has at least one linked TC.
        for idx, us_id in enumerate(us_ids):
            link_rows.append(
                TestCaseUserStory(test_case_id=tc_ids[idx % len(tc_ids)], user_story_id=us_id, project_id=project.id)
            )
        # Dense mapping: each TC linked to 1-2 US.
        for tc_id in tc_ids:
            primary_us = rnd.choice(us_ids)
            link_rows.append(TestCaseUserStory(test_case_id=tc_id, user_story_id=primary_us, project_id=project.id))
            if rnd.random() < 0.35:
                secondary_us = rnd.choice(us_ids)
                link_rows.append(
                    TestCaseUserStory(test_case_id=tc_id, user_story_id=secondary_us, project_id=project.id)
                )
        TestCaseUserStory.objects.bulk_create(link_rows, batch_size=2000, ignore_conflicts=True)

        actual_covered = (
            TestCaseUserStory.objects.filter(project_id=project.id).values("user_story_id").distinct().count()
        )
        return self._stats(us_total=us_count, tc_total=tc_count, covered_us=actual_covered)

    @staticmethod
    def _create_sections(project: Project, names: list[str]):
        rows = [Section(project=project, name=name) for name in names]
        Section.objects.bulk_create(rows, batch_size=200)
        return list(Section.objects.filter(project=project).order_by("id"))

    @staticmethod
    def _create_suites(project: Project, prefix: str, count: int):
        rows = [TestSuite(project=project, name=f"{prefix} {idx:02d}") for idx in range(1, count + 1)]
        TestSuite.objects.bulk_create(rows, batch_size=200)
        return list(TestSuite.objects.filter(project=project).order_by("id"))

    @staticmethod
    def _priority_from_index(idx: int) -> str:
        values = [
            TestCase.Priority.LOW,
            TestCase.Priority.MEDIUM,
            TestCase.Priority.HIGH,
            TestCase.Priority.CRITICAL,
        ]
        return values[idx % len(values)]

    @staticmethod
    def _stats(us_total: int, tc_total: int, covered_us: int):
        uncovered = max(us_total - covered_us, 0)
        pct = round((covered_us * 100.0) / us_total, 2) if us_total else 0.0
        return {
            "us_total": us_total,
            "tc_total": tc_total,
            "covered_us": covered_us,
            "uncovered_us": uncovered,
            "coverage_percent": pct,
        }
