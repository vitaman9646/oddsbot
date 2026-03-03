import aiohttp
import logging
from config import CFG

logger = logging.getLogger("odds_bot.telegram")


async def send_telegram(
    text: str,
    session: aiohttp.ClientSession = None,
):
    if not CFG.TELEGRAM_TOKEN or not CFG.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        return

    url = f"https://api.telegram.org/bot{CFG.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CFG.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        if session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    body = await r.text()
                    logger.error(f"TG error {r.status}: {body}")
        else:
            async with aiohttp.ClientSession() as tmp:
                async with tmp.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        body = await r.text()
                        logger.error(f"TG error {r.status}: {body}")
    except Exception as e:
        logger.error(f"TG send failed: {e}")
