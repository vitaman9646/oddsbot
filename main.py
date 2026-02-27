import asyncio
import aiohttp
import json
import logging
import os
import time

from config import CFG
from strategy.comparator import Comparator
from strategy.dedup import is_new_or_changed, clear_resolved
from notifications.telegram import send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(CFG.LOG_FILE),
    ]
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
    logger.info("Odds Bot v2.0 — VIRTUAL TRADING")
    logger.info(f"Min edge: {CFG.MIN_EDGE_PCT}%")
    logger.info(f"Scan interval: {CFG.SCAN_INTERVAL}s")
    logger.info("=" * 50)

    await send_telegram("?? Odds Bot v2.0 запущен\nРежим: VIRTUAL TRADING\nСпорт: Golf, NBA, NHL")

    async with aiohttp.ClientSession() as session:
        comparator = Comparator(session)
        scan_num = 0

        while True:
            scan_num += 1
            logger.info(f"--- Scan #{scan_num} ---")
            try:
                signals = await comparator.compare_all()

                active_keys = [
                    f"{s.sport}|{s.player}|{s.action}"
                    for s in signals
                ]
                clear_resolved(active_keys)

                new_signals = [
                    s for s in signals
                    if is_new_or_changed(s)
                ]

                if new_signals:
                    for signal in new_signals:
                        log_signal(signal)
                        await send_telegram(signal.format_alert(), session)
                        await asyncio.sleep(1)
                    logger.info(
                        f"Signals: {len(new_signals)} new, "
                        f"{len(signals) - len(new_signals)} duplicates skipped"
                    )
                else:
                    logger.info(
                        f"No new signals ({len(signals)} duplicates skipped)"
                    )

            except Exception as e:
                logger.error(f"Scan error: {e}")

            logger.info(f"Next scan in {CFG.SCAN_INTERVAL}s")
            await asyncio.sleep(CFG.SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
