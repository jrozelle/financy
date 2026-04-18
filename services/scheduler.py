"""
Scheduler APScheduler : refresh quotidien des cours.

Active uniquement si la variable d'environnement SCHEDULER_ENABLED=true.
Configurable :
- SCHEDULER_ENABLED : '1' | 'true' | 'yes' pour activer (defaut : false)
- SCHEDULER_HOUR    : heure du job (defaut : 21)
- SCHEDULER_MINUTE  : minute du job (defaut : 5)
- SCHEDULER_TZ      : timezone (defaut : Europe/Paris)

max_instances=1 previent les executions concurrentes (anti-double-run
en cas de redemarrage a l'heure pile).
"""
import logging
import os
import time

logger = logging.getLogger('financy.scheduler')

_scheduler = None


def is_enabled():
    return os.environ.get('SCHEDULER_ENABLED', '').lower() in ('1', 'true', 'yes')


def _job_refresh_prices():
    """Job APScheduler : refresh de tous les cours priceables."""
    from models import get_db
    from services.prices import refresh_securities, get_provider

    start = time.monotonic()
    provider = get_provider()
    try:
        with get_db() as conn:
            stats = refresh_securities(conn, provider=provider)
    except Exception:
        logger.exception('Scheduled prices refresh failed')
        return

    duration = time.monotonic() - start
    logger.info(
        'Scheduled prices refresh [%s] done in %.1fs — '
        'refreshed=%d resolved=%d errors=%d skipped=%d',
        provider.name, duration,
        stats.get('refreshed', 0),
        stats.get('resolved_tickers', 0),
        stats.get('errors', 0),
        stats.get('skipped', 0),
    )


def init_scheduler(app=None):
    """Initialise le scheduler si SCHEDULER_ENABLED=true.

    Appele une seule fois au demarrage de l'app. Idempotent.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not is_enabled():
        logger.info('Scheduler disabled (set SCHEDULER_ENABLED=true to enable)')
        return None

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning('apscheduler not installed; scheduler disabled')
        return None

    hour = int(os.environ.get('SCHEDULER_HOUR', 21))
    minute = int(os.environ.get('SCHEDULER_MINUTE', 5))
    tz = os.environ.get('SCHEDULER_TZ', 'Europe/Paris')

    _scheduler = BackgroundScheduler(timezone=tz)
    _scheduler.add_job(
        _job_refresh_prices,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        id='refresh_prices_daily',
        max_instances=1,       # anti-double-execution (lock implicite)
        coalesce=True,         # fusionne les runs rates
        misfire_grace_time=3600,
        replace_existing=True,
    )
    _scheduler.start()
    next_run = _scheduler.get_job('refresh_prices_daily').next_run_time
    logger.info('Scheduler started: refresh_prices_daily next at %s (%s)',
                next_run.isoformat() if next_run else 'n/a', tz)

    import atexit
    atexit.register(_shutdown_scheduler)
    return _scheduler


def _shutdown_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
            logger.info('Scheduler stopped')
        except Exception:
            pass
    _scheduler = None


def run_job_now():
    """Declenche manuellement le job (debug / tests)."""
    _job_refresh_prices()


def status():
    """Retourne le statut du scheduler pour diagnostic."""
    if _scheduler is None:
        return {'enabled': False, 'running': False}
    job = _scheduler.get_job('refresh_prices_daily') if _scheduler.running else None
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        'enabled': True,
        'running': _scheduler.running,
        'next_run': next_run,
        'timezone': str(_scheduler.timezone),
    }
