import aiohttp
import logging

from config import CFG

logger = logging.getLogger("odds_bot.telegram")


async def send_telegram(message: str, session: aiohttp.ClientSession = None):
    if not CFG.TELEGRAM_TOKEN or not CFG.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        return

    url = f"https://api.telegram.org/bot{CFG.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CFG.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        if session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(f"Telegram error: {resp.status}")
        else:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram error: {resp.status}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
