import asyncio
import aiohttp
import json
import logging
import os

from config import CFG
from strategy.comparator import Comparator
from strategy.dedup import is_new_or_changed, clear_resolved
from notifications.telegram import send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(CFG.LOG_FILE),
    ],
)
logger = logging.getLogger("odds_bot.main")


def log_signal(signal):
    os.makedirs("data", exist_ok=True)
    with open(CFG.TRADES_FILE, "a") as f:
        f.write(json.dumps(signal.to_dict()) + "\n")


async def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    logger.info("=" * 50)
    logger.info("Odds Bot v3.0 — VIRTUAL TRADING")
    logger.info(f"API keys: {len(CFG.ODDS_API_KEYS)}")
    logger.info(f"Min edge: {CFG.MIN_EDGE_PCT}%")
    logger.info(f"Min books: {CFG.MIN_BOOKS}")
    logger.info(f"Min PM volume: ${CFG.MIN_VOLUME_USD}")
    logger.info(f"Dedup threshold: {CFG.DEDUP_PRICE_THRESHOLD}")
    logger.info(f"Scan interval: {CFG.SCAN_INTERVAL}s")
    logger.info(f"Outright markets: {len(CFG.OUTRIGHT_MARKETS)}")
    logger.info("=" * 50)

    async with aiohttp.ClientSession() as session:
        comparator = Comparator(session)
        key_status = comparator.fetcher.key_manager.get_status_text()

        await send_telegram(
            "🤖 <b>Odds Bot v3.0 запущен</b>\n\n"
            f"Min edge: {CFG.MIN_EDGE_PCT}%\n"
            f"Markets: {len(CFG.OUTRIGHT_MARKETS)} outright\n"
            f"Scan: every {CFG.SCAN_INTERVAL}s\n\n"
            f"🔑 <b>API Keys:</b>\n<pre>{key_status}</pre>",
            session,
        )

        scan_num = 0
        KEYS_REPORT_EVERY = 10  # отчёт о ключах каждые N сканов

        while True:
            scan_num += 1
            logger.info(f"--- Scan #{scan_num} ---")

            # Проверяем есть ли ключи
            total_remaining = comparator.fetcher.key_manager.get_total_remaining()
            if total_remaining <= 0:
                msg = "🚨 ALL API KEYS EXHAUSTED! Bot paused until next month."
                logger.error(msg)
                await send_telegram(msg, session)
                # Ждём до конца дня и проверяем снова
                await asyncio.sleep(86400)
                continue

            try:
                signals = await comparator.compare_all()

                active_keys = [
                    f"{s.sport}|{s.player}|{s.action}"
                    for s in signals
                ]
                clear_resolved(active_keys)

                new_signals = [s for s in signals if is_new_or_changed(s)]

                if new_signals:
                    for sig in new_signals:
                        log_signal(sig)
                        await send_telegram(sig.format_alert(), session)
                        await asyncio.sleep(1)

                logger.info(
                    f"Results: {len(new_signals)} new, "
                    f"{len(signals) - len(new_signals)} dedup filtered, "
                    f"total: {len(signals)} | "
                    f"Keys left: {comparator.fetcher.key_manager.get_total_remaining()}"
                )

            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)

            # Периодический отчёт о ключах
            if scan_num % KEYS_REPORT_EVERY == 0:
                status = comparator.fetcher.key_manager.get_status_text()
                await send_telegram(
                    f"🔑 <b>Keys report (scan #{scan_num}):</b>\n"
                    f"<pre>{status}</pre>",
                    session,
                )

            logger.info(f"Next scan in {CFG.SCAN_INTERVAL}s")
            await asyncio.sleep(CFG.SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
