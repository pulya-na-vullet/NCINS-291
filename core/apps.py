import os
import sys

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from .scheduler import start_scheduler
        from . import signals  # noqa: F401

        command = sys.argv[1] if len(sys.argv) > 1 else ""
        skip_commands = {
            "makemigrations",
            "migrate",
            "collectstatic",
            "shell",
            "check",
            "test",
        }
        if command in skip_commands:
            return
        if os.environ.get("QMS_SKIP_SCHEDULER", "false").lower() == "true":
            return
        start_scheduler()
