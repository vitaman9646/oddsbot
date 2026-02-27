import json
import os
import time
import logging

logger = logging.getLogger("odds_bot.dedup")

SIGNALS_FILE = "data/seen_signals.json"


def _load_seen() -> dict:
    if not os.path.exists(SIGNALS_FILE):
        return {}
    try:
        with open(SIGNALS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_seen(seen: dict):
    os.makedirs("data", exist_ok=True)
    with open(SIGNALS_FILE, "w") as f:
        json.dump(seen, f)


def is_new_or_changed(signal, threshold_pct: float = 1.0) -> bool:
    """
    Возвращает True если сигнал новый или
    спред изменился более чем на threshold_pct.
    """
    seen = _load_seen()
    key = f"{signal.sport}|{signal.player}|{signal.action}"

    if key not in seen:
        seen[key] = {
            "spread_pct": signal.spread_pct,
            "ts": time.time(),
        }
        _save_seen(seen)
        logger.info(f"New signal: {key}")
        return True

    old_spread = seen[key]["spread_pct"]
    delta = abs(signal.spread_pct - old_spread)

    if delta >= threshold_pct:
        seen[key] = {
            "spread_pct": signal.spread_pct,
            "ts": time.time(),
        }
        _save_seen(seen)
        logger.info(
            f"Changed signal: {key} "
            f"{old_spread:+.1f}% -> {signal.spread_pct:+.1f}%"
        )
        return True

    logger.debug(f"Duplicate signal skipped: {key}")
    return False


def clear_resolved(active_keys: list[str]):
    """Удаляем из seen сигналы которых больше нет."""
    seen = _load_seen()
    removed = [k for k in seen if k not in active_keys]
    for k in removed:
        del seen[k]
        logger.info(f"Resolved signal removed: {k}")
    if removed:
        _save_seen(seen)
