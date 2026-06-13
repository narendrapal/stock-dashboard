"""
Background scheduler: runs rule checks and sends WhatsApp alerts on a cron schedule.
Uses APScheduler (in-process, no external cron daemon needed).
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import WHATSAPP_CONFIG, NOTIFICATION_RULES, WATCHLISTS
from analysis.screener import check_rules_for_symbol
from notifications.whatsapp import send_whatsapp, format_alert_message

logger = logging.getLogger(__name__)

_scheduler = None


def run_notification_check():
    """
    Core job: scans the configured watchlist against all enabled rules.
    Sends a WhatsApp message if any rule is triggered.
    """
    cfg = WHATSAPP_CONFIG
    if not cfg.get("enabled"):
        return

    watchlist_name = cfg.get("notify_watchlist", "My Watchlist")
    symbols = WATCHLISTS.get(watchlist_name, [])
    enabled_rules = [r for r in NOTIFICATION_RULES if r.get("enabled")]

    if not symbols or not enabled_rules:
        logger.info("No symbols or rules to check.")
        return

    logger.info(f"Running notification check for {len(symbols)} symbols, {len(enabled_rules)} rules...")
    all_alerts = []

    for sym in symbols:
        alerts = check_rules_for_symbol(sym, enabled_rules)
        all_alerts.extend(alerts)

    if all_alerts:
        msg = format_alert_message(all_alerts)
        logger.info(f"Sending {len(all_alerts)} alerts via WhatsApp...")
        send_whatsapp(cfg["phone"], cfg["api_key"], msg)
    else:
        logger.info("No alerts triggered.")


def start_scheduler(interval_minutes: int = None):
    """Start the background APScheduler. Safe to call multiple times (idempotent)."""
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.info("Scheduler already running.")
        return

    minutes = interval_minutes or WHATSAPP_CONFIG.get("cron_interval_minutes", 30)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_notification_check,
        trigger=IntervalTrigger(minutes=minutes),
        id="notification_check",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Scheduler started: checking every {minutes} minutes.")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


def get_scheduler_status() -> dict:
    global _scheduler
    if _scheduler and _scheduler.running:
        jobs = _scheduler.get_jobs()
        next_run = jobs[0].next_run_time if jobs else None
        return {"running": True, "next_run": str(next_run) if next_run else "N/A"}
    return {"running": False, "next_run": "N/A"}
