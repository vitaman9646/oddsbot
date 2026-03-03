import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import CFG
from strategy.key_manager import KeyManager

logger = logging.getLogger("odds_bot.odds_fetcher")


@dataclass
class OutrightOdds:
    team_name: str
    fair_prob: float
    num_books: int
    raw_odds: list


OUTRIGHT_SPORTS = list(CFG.OUTRIGHT_MARKETS.keys())


def remove_vig(outcomes: list[dict]) -> dict[str, float]:
    """Снимаем маржу букмекера multiplicative методом."""
    implied = {}
    for o in outcomes:
        name = o.get("name", "")
        price = o.get("price", 0)
        if price > 1.0:
            implied[name] = 1 / price
        else:
            implied[name] = 0

    total = sum(implied.values())
    if total == 0:
        return {}

    fair = {name: prob / total for name, prob in implied.items()}
    return fair


class OddsFetcher:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.key_manager = KeyManager()

    async def _api_request(self, url: str, params: dict) -> Optional[dict]:
        """Делаем запрос с автоматической ротацией ключей."""
        for attempt in range(len(self.key_manager.keys)):
            key = self.key_manager.get_current_key()
            if key is None:
                logger.error("No available API keys!")
                return None

            params["apiKey"] = key

            try:
                async with self.session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    # Обновляем remaining из заголовков
                    self.key_manager.update_from_response(key, dict(r.headers))

                    if r.status == 200:
                        remaining = r.headers.get("x-requests-remaining", "?")
                        logger.info(
                            f"API OK | Key ...{key[-6:]} | "
                            f"Remaining: {remaining}"
                        )
                        return await r.json()

                    elif r.status in (401, 429):
                        self.key_manager.report_error(key, r.status)
                        logger.warning(
                            f"Key ...{key[-6:]} got {r.status}, rotating..."
                        )
                        continue

                    elif r.status == 422:
                        body = await r.text()
                        logger.warning(f"API 422: {body}")
                        return None

                    else:
                        body = await r.text()
                        logger.error(f"API {r.status}: {body}")
                        return None

            except asyncio.TimeoutError:
                logger.warning(f"API timeout with key ...{key[-6:]}")
                return None
            except Exception as e:
                logger.error(f"API error: {e}")
                return None

        logger.error("All keys exhausted during request")
        return None

    async def fetch_outright(self, sport_key: str) -> list[OutrightOdds]:
        """Получаем outright коэффициенты."""
        url = f"{CFG.ODDS_API_BASE}/sports/{sport_key}/odds"
        params = {
            "regions": "us,eu,uk",
            "markets": "outrights",
            "oddsFormat": "decimal",
        }

        data = await self._api_request(url, params)
        if not data:
            return []

        # Собираем fair_prob от каждого букмекера для каждой команды
        team_probs: dict[str, list[float]] = {}
        team_raw: dict[str, list] = {}

        events = data if isinstance(data, list) else [data]

        for event in events:
            for bk in event.get("bookmakers", []):
                bk_name = bk.get("key", "")
                for market in bk.get("markets", []):
                    if market.get("key") != "outrights":
                        continue

                    fair = remove_vig(market.get("outcomes", []))
                    for team, prob in fair.items():
                        if team not in team_probs:
                            team_probs[team] = []
                            team_raw[team] = []
                        team_probs[team].append(prob)
                        team_raw[team].append({
                            "book": bk_name,
                            "prob": round(prob, 4),
                        })

        # Средняя fair_prob по всем букмекерам
        results = []
        for team, probs in team_probs.items():
            avg_prob = sum(probs) / len(probs)
            results.append(OutrightOdds(
                team_name=team,
                fair_prob=avg_prob,
                num_books=len(probs),
                raw_odds=team_raw.get(team, []),
            ))

        logger.info(
            f"{sport_key}: {len(results)} teams from "
            f"{len(events)} events | "
            f"Keys remaining: {self.key_manager.get_total_remaining()}"
        )
        return results
