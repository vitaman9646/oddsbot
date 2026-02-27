import asyncio
import aiohttp
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from config import CFG
from strategy.odds_fetcher import OddsFetcher, OUTRIGHT_SPORTS
from strategy.matcher import match_teams_bulk

logger = logging.getLogger("odds_bot.comparator")

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SPORT_PM_KEYWORDS = {
    "basketball_nba_championship_winner": ["NBA", "Champion"],
    "icehockey_nhl_championship_winner":  ["NHL", "Stanley Cup"],
    "golf_masters_tournament_winner":     ["Masters", "Winner"],
}


def is_placeholder(name: str) -> bool:
    if name.lower().strip() in {"any other player", "field", "other"}:
        return True
    if re.match(r"^Player [A-Z]{1,2}$", name, re.IGNORECASE):
        return True
    return False


@dataclass
class Signal:
    sport: str
    player: str
    bk_prob: float
    pm_price: float
    spread_pct: float
    num_books: int
    action: str       # "BUY NO" или "BUY YES"
    edge_pct: float
    match_method: str

    def format_alert(self) -> str:
        icon = "??" if self.action == "BUY NO" else "??"
        return (
            f"{icon} <b>SIGNAL: {self.sport}</b>\n\n"
            f"?? {self.player}\n\n"
            f"?? Букмекеры: {self.bk_prob:.1%} ({self.num_books} books)\n"
            f"?? Polymarket: {self.pm_price:.1%}\n"
            f"?? Спред: {self.spread_pct:+.1f}%\n\n"
            f"✅ Действие: <b>{self.action}</b> @ ${self.pm_price:.2f}\n"
            f"?? Edge: ~{self.edge_pct:.1f}% ROI\n\n"
            f"⚠️ Virtual mode — no real trade"
        )

    def to_dict(self) -> dict:
        return {
            "ts": time.time(),
            "sport": self.sport,
            "player": self.player,
            "bk_prob": round(self.bk_prob, 4),
            "pm_price": round(self.pm_price, 4),
            "spread_pct": round(self.spread_pct, 2),
            "num_books": self.num_books,
            "action": self.action,
            "edge_pct": round(self.edge_pct, 2),
            "match_method": self.match_method,
            "status": "virtual",
        }


class Comparator:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.fetcher = OddsFetcher(session)

    async def _fetch_pm_event(self, keywords: list[str]) -> dict | None:
        async with self.session.get(
            CFG.GAMMA_EVENTS_API,
            params={"active": "true", "closed": "false", "limit": "500"},
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            events = await r.json()
        return next((
            e for e in events
            if all(k.lower() in e.get("title", "").lower() for k in keywords)
        ), None)

    def _parse_pm_players(self, event: dict) -> dict[str, float]:
        players = {}
        for m in event.get("markets", []):
            match = re.search(
                r"Will (?:the )?(.+?) win", m.get("question", ""), re.IGNORECASE
            )
            if not match:
                continue
            name = match.group(1).strip()
            if is_placeholder(name):
                continue
            try:
                price = float(json.loads(m.get("outcomePrices", "[]"))[0])
                players[name] = price
            except Exception:
                pass
        return players

    async def compare_sport(self, sport_key: str) -> list[Signal]:
        keywords = SPORT_PM_KEYWORDS.get(sport_key)
        if not keywords:
            return []

        odds = await self.fetcher.fetch_outright(sport_key)
        if not odds:
            return []

        pm_event = await self._fetch_pm_event(keywords)
        if not pm_event:
            logger.warning(f"No PM event for {sport_key}")
            return []

        bk_teams = {o.team_name: o for o in odds}
        pm_players = self._parse_pm_players(pm_event)
        matched = match_teams_bulk(list(bk_teams.keys()), list(pm_players.keys()))

        signals = []
        for bk_name, result in matched.items():
            bk = bk_teams[bk_name]
            pm_price = pm_players.get(result.polymarket_name, 0)
            if pm_price <= 0:
                continue

            spread = bk.fair_prob - pm_price
            spread_pct = spread * 100

            if abs(spread_pct) < CFG.MIN_EDGE_PCT:
                continue
            if bk.num_books < 3:
                continue

            action = "BUY NO" if spread < 0 else "BUY YES"
            no_price = 1 - pm_price
            yes_price = pm_price

            if action == "BUY NO":
                fair_no = 1 - bk.fair_prob
                edge_pct = (fair_no / no_price - 1) * 100
            else:
                edge_pct = (bk.fair_prob / yes_price - 1) * 100

            signals.append(Signal(
                sport=OUTRIGHT_SPORTS.get(sport_key, sport_key),
                player=bk_name,
                bk_prob=bk.fair_prob,
                pm_price=pm_price,
                spread_pct=spread_pct,
                num_books=bk.num_books,
                action=action,
                edge_pct=edge_pct,
                match_method=result.method,
            ))

        signals.sort(key=lambda x: abs(x.spread_pct), reverse=True)
        logger.info(f"{sport_key}: {len(signals)} signals found")
        return signals

    async def compare_all(self) -> list[Signal]:
        all_signals = []
        for sport_key in SPORT_PM_KEYWORDS:
            try:
                signals = await self.compare_sport(sport_key)
                all_signals.extend(signals)
            except Exception as e:
                logger.error(f"Compare error {sport_key}: {e}")
            await asyncio.sleep(0.5)
        return all_signals
