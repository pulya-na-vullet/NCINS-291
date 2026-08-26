#!/usr/bin/env python3
"""Start QMS: always apply migrations, then serve the app."""

from __future__ import annotations

import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qms_django.settings")
# `python app.py` is meant to run locally without PostgreSQL.
os.environ.setdefault("USE_SQLITE", "true")


def _run_django(args: list[str]) -> None:
    original_argv = sys.argv
    sys.argv = args
    try:
        from django.core.management import execute_from_command_line

        execute_from_command_line(args)
    finally:
        sys.argv = original_argv


def main() -> None:
    host = os.environ.get("QMS_HOST", "0.0.0.0")
    port = os.environ.get("QMS_PORT", "8000")

    print("QMS: applying database migrations...", flush=True)
    os.environ["QMS_SKIP_SCHEDULER"] = "true"
    _run_django(["manage.py", "migrate", "--noinput"])
    os.environ.pop("QMS_SKIP_SCHEDULER", None)

    from core.scheduler import start_scheduler

    start_scheduler()

    print(f"QMS: starting server at http://127.0.0.1:{port}/", flush=True)
    print("QMS: login demo users: admin / admin, analyst / analyst, tester / tester", flush=True)
    _run_django(["manage.py", "runserver", "--noreload", f"{host}:{port}"])


if __name__ == "__main__":
    main()
