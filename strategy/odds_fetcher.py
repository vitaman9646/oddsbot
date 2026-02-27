import asyncio
import aiohttp
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from config import CFG

logger = logging.getLogger("odds_bot.odds_fetcher")

TRUSTED_BOOKMAKERS = {
    "pinnacle", "draftkings", "fanduel", "betmgm",
    "williamhill", "bet365", "unibet_eu", "betonlineag",
    "sportsbet", "everygame", "betclic", "marathon_bet",
    "betrivers", "pointsbet", "lowvig",
}

MAX_OVERROUND = {
    "basketball_nba_championship_winner": 40,
    "icehockey_nhl_championship_winner": 50,
    "golf_masters_tournament_winner": 120,
    "soccer_fifa_world_cup_winner": 80,
}

OUTRIGHT_SPORTS = {
    "basketball_nba_championship_winner": "NBA Champion",
    "golf_masters_tournament_winner": "The Masters - Winner",
    "icehockey_nhl_championship_winner": "NHL Stanley Cup Champion",
    "soccer_fifa_world_cup_winner": "FIFA World Cup Winner",
}


@dataclass
class TeamOdds:
    sport_key: str
    sport_title: str
    team_name: str
    fair_prob: float
    raw_odds: float  # Добавлено: оригинальные odds для отладки
    source: str
    num_books: int = 1  # Сколько букмекеров в среднем


def remove_vig(odds_list: list[float]) -> list[float]:
    """Убираем маржу букмекера из списка decimal odds"""
    if not odds_list:
        return []

    if any(o <= 1.0 for o in odds_list):
        logger.warning(f"Invalid decimal odds (<=1.0): {odds_list}")
        odds_list = [o for o in odds_list if o > 1.0]
        if not odds_list:
            return []

    implied = [1.0 / o for o in odds_list]
    total = sum(implied)

    overround_pct = (total - 1.0) * 100
    if overround_pct > 50:
        logger.warning(f"High overround: {overround_pct:.1f}% — data suspect")
    elif overround_pct < -5:
        logger.warning(f"Negative overround: {overround_pct:.1f}% — data suspect")

    logger.debug(f"Overround: {overround_pct:.1f}%")
    return [i / total for i in implied]


class OddsFetcher:
    CACHE_TTL = 3600 * 4  # 4 часа по умолчанию

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self._cache: dict[str, list[TeamOdds]] = {}
        self._cache_time: dict[str, float] = {}

    async def fetch_outright(
        self, sport_key: str, force: bool = False
    ) -> list[TeamOdds]:
        # Проверяем кэш
        if not force and sport_key in self._cache_time:
            age = time.time() - self._cache_time[sport_key]
            if age < self.CACHE_TTL:
                logger.debug(
                    f"Cache hit for {sport_key} "
                    f"(age: {age/60:.0f} min)"
                )
                return self._cache[sport_key]

        url = f"{CFG.ODDS_API_BASE}/sports/{sport_key}/odds"
        params = {
            "apiKey": CFG.ODDS_API_KEY,
            "regions": "eu,uk,us,au",
            "markets": "outrights",
            "oddsFormat": "decimal",
        }

        EXCLUDED_BOOKMAKERS = {
            "betfair_ex_uk", "betfair_ex_eu", "betfair_ex_au",
        }

        try:
            async with self.session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                remaining = resp.headers.get(
                    "x-requests-remaining", "?"
                )
                used = resp.headers.get("x-requests-used", "?")

                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        f"Odds API {resp.status} for {sport_key}: "
                        f"{body[:200]}"
                    )
                    return self._cache.get(sport_key, [])

                data = await resp.json()
                logger.info(
                    f"Odds API: {sport_key} — "
                    f"{len(data)} events, "
                    f"requests used/remaining: {used}/{remaining}"
                )

        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {sport_key}")
            return self._cache.get(sport_key, [])
        except Exception as e:
            logger.error(f"Odds fetch error for {sport_key}: {e}")
            return self._cache.get(sport_key, [])

        if not data:
            logger.warning(f"No data returned for {sport_key}")
            return []

        # Собираем данные со ВСЕХ букмекеров
        raw_by_team: dict[str, list[tuple[float, float]]] = {}
        # team -> [(fair_prob, raw_odd), ...]
        bookmaker_count = 0

        for event in data:
            for bookmaker in event.get("bookmakers", []):
                bk_key = bookmaker.get("key", "unknown")

                if bk_key not in TRUSTED_BOOKMAKERS:
                    logger.debug(f"Skipping untrusted: {bk_key}")
                    continue
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "outrights":
                        continue

                    outcomes = market.get("outcomes", [])
                    if not outcomes:
                        continue

                    # Фильтр по overround
                    odds_values = [o["price"] for o in outcomes]
                    implied = [1.0/o for o in odds_values if o > 1.0]
                    overround = (sum(implied) - 1.0) * 100
                    max_or = MAX_OVERROUND.get(sport_key, 50)
                    if overround > max_or:
                        logger.debug(f"Skipping {bk_key}: OR {overround:.1f}%")
                        continue
                    fair_probs = remove_vig(odds_values)

                    if not fair_probs:
                        continue

                    if bk_key in EXCLUDED_BOOKMAKERS:
                        logger.debug(f"Skipping {bk_key} (lay odds)")
                        continue

                    overround = (sum(1/o for o in odds_values if o > 1.0) - 1) * 100
                    if overround > 80:
                        logger.warning(f"Skipping {bk_key}: overround {overround:.1f}%")
                        continue

                    bookmaker_count += 1

                    for outcome, prob, raw_odd in zip(
                        outcomes, fair_probs, odds_values
                    ):
                        team = outcome["name"]
                        if team not in raw_by_team:
                            raw_by_team[team] = []
                        raw_by_team[team].append((prob, raw_odd))

                    break  # один market "outrights" на букмекера

        logger.info(
            f"{sport_key}: {bookmaker_count} bookmakers, "
            f"{len(raw_by_team)} teams"
        )

        # Усредняем по всем букмекерам
        averaged = []
        for team, prob_odds_list in raw_by_team.items():
            probs = [p for p, _ in prob_odds_list]
            odds = [o for _, o in prob_odds_list]

            avg_prob = sum(probs) / len(probs)
            avg_odd = sum(odds) / len(odds)

            averaged.append(
                TeamOdds(
                    sport_key=sport_key,
                    sport_title=OUTRIGHT_SPORTS.get(
                        sport_key, sport_key
                    ),
                    team_name=team,
                    fair_prob=avg_prob,
                    raw_odds=avg_odd,
                    source="averaged",
                    num_books=len(probs),
                )
            )

        # Сортируем по вероятности (фавориты сверху)
        averaged.sort(key=lambda x: x.fair_prob, reverse=True)

        # Валидация: сумма вероятностей должна быть ~1.0
        total_prob = sum(t.fair_prob for t in averaged)
        if averaged and abs(total_prob - 1.0) > 0.05:
            logger.warning(
                f"{sport_key}: total fair prob = {total_prob:.3f} "
                f"(expected ~1.0)"
            )

        # Кэшируем
        self._cache[sport_key] = averaged
        self._cache_time[sport_key] = time.time()

        return averaged

    async def fetch_all(self) -> dict[str, list[TeamOdds]]:
        """Получаем odds по всем спортам"""
        result = {}
        for sport_key in OUTRIGHT_SPORTS:
            odds = await self.fetch_outright(sport_key)
            if odds:
                result[sport_key] = odds
                # Логируем топ-5 фаворитов
                top5 = odds[:5]
                for t in top5:
                    logger.info(
                        f"  {t.team_name}: "
                        f"{t.fair_prob:.1%} "
                        f"(avg of {t.num_books} books)"
                    )
            await asyncio.sleep(0.5)  # rate limiting

        logger.info(
            f"Fetched odds for {len(result)}/{len(OUTRIGHT_SPORTS)} sports"
        )
        return result

    def get_cached(
        self, sport_key: str
    ) -> Optional[list[TeamOdds]]:
        """Получить кэшированные данные без запроса"""
        return self._cache.get(sport_key)

    def cache_age(self, sport_key: str) -> Optional[float]:
        """Возраст кэша в секундах"""
        if sport_key in self._cache_time:
            return time.time() - self._cache_time[sport_key]
        return None
