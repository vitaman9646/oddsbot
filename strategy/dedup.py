import logging
from typing import Optional

from config import CFG

logger = logging.getLogger("odds_bot.dedup")

# {signal_key: {"entry_price": float, "edge_pct": float, "action": str}}
_cache: dict[str, dict] = {}


def _make_key(signal) -> str:
    return f"{signal.sport}|{signal.player}|{signal.action}"


def is_new_or_changed(signal) -> bool:
    """
    Возвращает True если сигнал новый или существенно изменился.
    Порог изменения: DEDUP_PRICE_THRESHOLD (по умолчанию 0.02 = 2 цента).
    """
    key = _make_key(signal)
    prev = _cache.get(key)

    if prev is None:
        # Новый сигнал
        _cache[key] = {
            "entry_price": signal.entry_price,
            "edge_pct": signal.edge_pct,
            "action": signal.action,
        }
        logger.debug(f"New signal: {key}")
        return True

    # Проверяем существенное изменение цены
    price_diff = abs(signal.entry_price - prev["entry_price"])
    if price_diff < CFG.DEDUP_PRICE_THRESHOLD:
        return False

    # Цена существенно изменилась — обновляем и пропускаем
    logger.debug(
        f"Updated signal: {key} | "
        f"price {prev['entry_price']:.3f} → {signal.entry_price:.3f} | "
        f"edge {prev['edge_pct']:.1f}% → {signal.edge_pct:.1f}%"
    )
    _cache[key] = {
        "entry_price": signal.entry_price,
        "edge_pct": signal.edge_pct,
        "action": signal.action,
    }
    return True


def clear_resolved(active_keys: list[str]):
    """Удаляем из кэша сигналы которых больше нет в сканировании."""
    active_set = set(active_keys)
    stale = [k for k in _cache if k not in active_set]
    for k in stale:
        logger.debug(f"Cleared stale signal: {k}")
        del _cache[k]
