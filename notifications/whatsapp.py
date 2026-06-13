"""
WhatsApp notifications via CallMeBot (completely FREE).

Setup steps:
1. Save +34 644 59 21 64 in your phone contacts as "CallMeBot"
2. Send this WhatsApp message to that number:
   "I allow callmebot to send me messages"
3. You'll receive an API key back within a few minutes.
4. Edit WHATSAPP_CONFIG in config.py with your phone and api_key.
"""

import logging
import urllib.parse
import requests

logger = logging.getLogger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def send_whatsapp(phone: str, api_key: str, message: str) -> bool:
    """
    Send a WhatsApp message via CallMeBot.
    Returns True on success, False on failure.
    """
    try:
        encoded_msg = urllib.parse.quote(message)
        url = f"{CALLMEBOT_URL}?phone={phone}&text={encoded_msg}&apikey={api_key}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            logger.info(f"WhatsApp sent to {phone}")
            return True
        else:
            logger.error(f"CallMeBot error {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")
        return False


def format_alert_message(alerts: list) -> str:
    """Format a list of triggered alerts into a WhatsApp message."""
    if not alerts:
        return ""
    lines = ["📈 *Market Alert* 📈\n"]
    for alert in alerts:
        lines.append(
            f"• *{alert['symbol']}*: {alert['rule']}\n"
            f"  {alert['field']} = {alert['actual']} (threshold: {alert['threshold']})"
        )
    return "\n".join(lines)
