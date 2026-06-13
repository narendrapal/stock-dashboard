"""
Standalone alert checker — runs as a GitHub Actions cron job.
Reads config from environment variables (set as GitHub Secrets).

Usage (local test):
    WHATSAPP_PHONE=+91XXX WHATSAPP_API_KEY=abc NOTIFY_WATCHLIST="Nifty 50" python notifications/check_alerts.py
"""

import os
import sys
import logging

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import NOTIFICATION_RULES, NSE_DYNAMIC_INDICES, STATIC_WATCHLISTS
from data.nifty import fetch_index_symbols
from analysis.screener import check_rules_for_symbol
from notifications.whatsapp import send_whatsapp, format_alert_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    phone = os.environ.get("WHATSAPP_PHONE", "")
    api_key = os.environ.get("WHATSAPP_API_KEY", "")
    watchlist_name = os.environ.get("NOTIFY_WATCHLIST", "Nifty 50")
    enabled_str = os.environ.get("WHATSAPP_ENABLED", "true")
    enabled = enabled_str.lower() in ("true", "1", "yes")

    if not enabled:
        logger.info("WhatsApp notifications disabled (WHATSAPP_ENABLED != true). Exiting.")
        return

    if not phone or not api_key:
        logger.error("WHATSAPP_PHONE and WHATSAPP_API_KEY must be set as environment variables / GitHub Secrets.")
        sys.exit(1)

    # Resolve symbols
    if watchlist_name in NSE_DYNAMIC_INDICES:
        symbols = fetch_index_symbols(watchlist_name)
    else:
        symbols = STATIC_WATCHLISTS.get(watchlist_name, [])

    if not symbols:
        logger.error(f"No symbols found for watchlist: {watchlist_name}")
        sys.exit(1)

    enabled_rules = [r for r in NOTIFICATION_RULES if r.get("enabled")]
    if not enabled_rules:
        logger.info("No enabled rules. Exiting.")
        return

    logger.info(f"Checking {len(symbols)} symbols in '{watchlist_name}' against {len(enabled_rules)} rules...")
    all_alerts = []

    for sym in symbols:
        try:
            alerts = check_rules_for_symbol(sym, enabled_rules)
            all_alerts.extend(alerts)
        except Exception as e:
            logger.warning(f"Error checking {sym}: {e}")

    logger.info(f"Found {len(all_alerts)} alert(s).")

    if all_alerts:
        msg = format_alert_message(all_alerts)
        logger.info("Sending WhatsApp notification...")
        ok = send_whatsapp(phone, api_key, msg)
        if not ok:
            logger.error("WhatsApp send failed.")
            sys.exit(1)
    else:
        logger.info("No alerts to send.")


if __name__ == "__main__":
    main()
