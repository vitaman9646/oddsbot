import aiohttp
import json
import logging
import re
from typing import Optional

from config import CFG

logger = logging.getLogger("odds_bot.polymarket")

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _is_placeholder(name: str) -> bool:
    low = name.lower().strip()
    if low in {"any other player", "field", "other", "the field"}:
        return True
    if re.match(r"^player [a-z]{1,2}$", low):
        return True
    return False


class PolymarketClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self._cache: dict[str, dict] = {}

    async def search_event(self, keywords: list[str]) -> Optional[dict]:
        """Ищем event на Polymarket по ключевым словам."""
        cache_key = "|".join(keywords)
        try:
            async with self.session.get(
                CFG.GAMMA_EVENTS_API,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": "500",
                },
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    logger.warning(f"PM API status {r.status}")
                    return self._cache.get(cache_key)
                events = await r.json()
        except Exception as e:
            logger.error(f"PM API error: {e}")
            return self._cache.get(cache_key)

        for e in events:
            title = e.get("title", "").lower()
            if all(k.lower() in title for k in keywords):
                self._cache[cache_key] = e
                return e

        logger.warning(f"PM event not found for keywords: {keywords}")
        return None

    def parse_outright_prices(self, event: dict) -> dict[str, dict]:
        """
        Парсим outright event.
        Возвращает {player_name: {"yes": float, "no": float, "volume": float}}
        """
        players = {}
        for m in event.get("markets", []):
            question = m.get("question", "")

            # Паттерны: "Will X win...", "Will the X win..."
            match = re.search(
                r"Will (?:the )?(.+?) win",
                question,
                re.IGNORECASE,
            )
            if not match:
                continue

            name = match.group(1).strip()
            if _is_placeholder(name):
                continue

            try:
                prices = json.loads(m.get("outcomePrices", "[]"))
                yes_price = float(prices[0])
                no_price = float(prices[1]) if len(prices) > 1 else 1 - yes_price

                # Объём торгов
                volume = float(m.get("volume", 0) or 0)

                players[name] = {
                    "yes": yes_price,
                    "no": no_price,
                    "volume": volume,
                    "condition_id": m.get("conditionId", ""),
                }
            except Exception:
                pass

        return players

    async def search_game_events(self, team1: str, team2: str) -> list[dict]:
        """Ищем матчевые рынки (moneyline) на PM."""
        try:
            async with self.session.get(
                CFG.GAMMA_EVENTS_API,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": "100",
                    "tag": "sports",
                },
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    return []
                events = await r.json()
        except Exception as e:
            logger.error(f"PM game search error: {e}")
            return []

        results = []
        t1, t2 = team1.lower(), team2.lower()
        for e in events:
            title = e.get("title", "").lower()
            if (t1 in title and t2 in title) or \
               (t1.split()[-1] in title and t2.split()[-1] in title):
                results.append(e)

        return results
