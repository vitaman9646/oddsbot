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
    logger.info(f"Min edge: {CFG.MIN_EDGE_PCT}%")
    logger.info(f"Min books: {CFG.MIN_BOOKS}")
    logger.info(f"Min PM volume: ${CFG.MIN_VOLUME_USD}")
    logger.info(f"Dedup threshold: {CFG.DEDUP_PRICE_THRESHOLD}")
    logger.info(f"Scan interval: {CFG.SCAN_INTERVAL}s")
    logger.info(f"Outright markets: {len(CFG.OUTRIGHT_MARKETS)}")
    logger.info("=" * 50)

    async with aiohttp.ClientSession() as session:
        await send_telegram(
            "🤖 Odds Bot v3.0 запущен\n"
            f"Режим: VIRTUAL TRADING\n"
            f"Min edge: {CFG.MIN_EDGE_PCT}%\n"
            f"Markets: {len(CFG.OUTRIGHT_MARKETS)} outright",
            session,
        )

        comparator = Comparator(session)
        scan_num = 0

        while True:
            scan_num += 1
            logger.info(f"--- Scan #{scan_num} ---")
            try:
                signals = await comparator.compare_all()

                # Обновляем дедупликацию
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
                    f"Results: {len(new_signals)} new signals, "
                    f"{len(signals) - len(new_signals)} filtered by dedup, "
                    f"total candidates: {len(signals)}"
                )

            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)

            logger.info(f"Next scan in {CFG.SCAN_INTERVAL}s")
            await asyncio.sleep(CFG.SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
