import atexit
import os

from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings

from .services import bulk_refresh_matrices

_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    if os.environ.get("DISABLE_QMS_SCHEDULER", "false").lower() == "true":
        return
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    sqlite_scheduler_allowed = os.environ.get("ENABLE_QMS_SQLITE_SCHEDULER", "false").lower() == "true"
    if "sqlite" in engine and not sqlite_scheduler_allowed:
        # SQLite uses a coarse write lock; background refresh collides with web requests and
        # causes "database is locked" errors. Disable by default for local/dev SQLite runs.
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    # Critical production fix: refresh matrices every 15 minutes, not every second.
    _scheduler.add_job(
        bulk_refresh_matrices,
        "interval",
        minutes=15,
        id="traceability-matrix-refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    atexit.register(_scheduler.shutdown)
