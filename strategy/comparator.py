import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from config import CFG
from strategy.odds_fetcher import OddsFetcher, OUTRIGHT_SPORTS
from strategy.matcher import match_teams_bulk
from sources.polymarket import PolymarketClient

import aiohttp

logger = logging.getLogger("odds_bot.comparator")


@dataclass
class Signal:
    sport: str
    player: str
    bk_prob: float          # fair probability (vig removed)
    pm_yes: float           # PM YES price
    pm_no: float            # PM NO price
    spread_pct: float       # разница fair_prob vs pm_price
    num_books: int
    action: str             # "BUY YES" or "BUY NO"
    edge_pct: float         # expected ROI %
    match_method: str
    pm_volume: float = 0.0
    entry_price: float = 0.0  # цена входа (yes или no)

    def format_alert(self) -> str:
        icon = "🔴" if self.action == "BUY NO" else "🟢"
        return (
            f"{icon} <b>SIGNAL: {self.sport}</b>\n\n"
            f"👤 {self.player}\n\n"
            f"📊 Букмекеры fair prob: {self.bk_prob:.1%} ({self.num_books} books)\n"
            f"🔵 Polymarket YES: {self.pm_yes:.1%} | NO: {self.pm_no:.1%}\n"
            f"📏 Spread: {self.spread_pct:+.1f}%\n\n"
            f"✅ Действие: <b>{self.action}</b> @ ${self.entry_price:.3f}\n"
            f"💰 Edge: ~{self.edge_pct:.1f}% ROI\n"
            f"📈 PM Volume: ${self.pm_volume:,.0f}\n\n"
            f"⚠️ Virtual mode — no real trade"
        )

    def to_dict(self) -> dict:
        return {
            "ts": time.time(),
            "sport": self.sport,
            "player": self.player,
            "bk_prob": round(self.bk_prob, 4),
            "pm_yes": round(self.pm_yes, 4),
            "pm_no": round(self.pm_no, 4),
            "entry_price": round(self.entry_price, 4),
            "spread_pct": round(self.spread_pct, 2),
            "num_books": self.num_books,
            "action": self.action,
            "edge_pct": round(self.edge_pct, 2),
            "match_method": self.match_method,
            "pm_volume": round(self.pm_volume, 2),
            "status": "virtual",
        }


class Comparator:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.fetcher = OddsFetcher(session)
        self.pm = PolymarketClient(session)

    def _calculate_edge(
        self, bk_fair_prob: float, pm_yes: float, pm_no: float
    ) -> Optional[dict]:
        """
        Рассчитывает edge для BUY YES и BUY NO.
        Возвращает лучший вариант или None.

        Логика:
        - BUY YES выгодно когда bk_fair_prob > pm_yes
          (букмекер считает вероятность ВЫШЕ чем PM цена)
          edge_yes = bk_fair_prob / pm_yes - 1

        - BUY NO выгодно когда (1 - bk_fair_prob) > pm_no
          (букмекер считает вер-ть проигрыша ВЫШЕ чем PM NO цена)
          → то же что bk_fair_prob < (1 - pm_no)
          → то же что bk_fair_prob < pm_yes  ← нет! pm_yes + pm_no ≈ 1
          edge_no = (1 - bk_fair_prob) / pm_no - 1
        """
        fair_yes = bk_fair_prob
        fair_no = 1 - bk_fair_prob

        # Edge для BUY YES: fair_yes > pm_yes → PM недооценивает
        edge_yes_pct = (fair_yes / pm_yes - 1) * 100 if pm_yes > 0 else -999

        # Edge для BUY NO: fair_no > pm_no → PM переоценивает YES
        edge_no_pct = (fair_no / pm_no - 1) * 100 if pm_no > 0 else -999

        # Выбираем лучший вариант
        if edge_yes_pct >= edge_no_pct and edge_yes_pct >= CFG.MIN_EDGE_PCT:
            return {
                "action": "BUY YES",
                "edge_pct": edge_yes_pct,
                "entry_price": pm_yes,
                "spread_pct": (fair_yes - pm_yes) * 100,
            }
        elif edge_no_pct >= CFG.MIN_EDGE_PCT:
            return {
                "action": "BUY NO",
                "edge_pct": edge_no_pct,
                "entry_price": pm_no,
                "spread_pct": (fair_no - pm_no) * 100,
            }

        return None

    async def compare_outright(self, sport_key: str) -> list[Signal]:
        """Сравниваем outright market (NBA champion, Masters winner и т.д.)"""
        market_cfg = CFG.OUTRIGHT_MARKETS.get(sport_key)
        if not market_cfg:
            return []

        # 1. Получаем коэффициенты букмекеров
        odds = await self.fetcher.fetch_outright(sport_key)
        if not odds:
            logger.info(f"{sport_key}: no odds data")
            return []

        # 2. Получаем цены Polymarket
        pm_event = await self.pm.search_event(market_cfg["keywords"])
        if not pm_event:
            logger.warning(f"{sport_key}: no PM event")
            return []

        pm_players = self.pm.parse_outright_prices(pm_event)
        if not pm_players:
            logger.warning(f"{sport_key}: no PM players parsed")
            return []

        # 3. Матчим имена
        bk_teams = {o.team_name: o for o in odds}
        matched = match_teams_bulk(
            list(bk_teams.keys()),
            list(pm_players.keys()),
        )

        # 4. Считаем edge для каждого матча
        signals = []
        for bk_name, result in matched.items():
            bk = bk_teams[bk_name]
            pm_data = pm_players.get(result.polymarket_name)
            if not pm_data:
                continue

            pm_yes = pm_data["yes"]
            pm_no = pm_data["no"]
            pm_volume = pm_data["volume"]

            # --- Фильтры ---
            # Минимум букмекеров
            if bk.num_books < CFG.MIN_BOOKS:
                continue

            # PM цена в разумных пределах
            if pm_yes < CFG.MIN_PM_PRICE or pm_yes > CFG.MAX_PM_PRICE:
                continue

            # Минимальный объём на PM
            if pm_volume < CFG.MIN_VOLUME_USD:
                continue

            # --- Расчёт edge ---
            edge_result = self._calculate_edge(bk.fair_prob, pm_yes, pm_no)
            if not edge_result:
                continue

            signals.append(Signal(
                sport=market_cfg["display"],
                player=bk_name,
                bk_prob=bk.fair_prob,
                pm_yes=pm_yes,
                pm_no=pm_no,
                spread_pct=edge_result["spread_pct"],
                num_books=bk.num_books,
                action=edge_result["action"],
                edge_pct=edge_result["edge_pct"],
                match_method=result.method,
                pm_volume=pm_volume,
                entry_price=edge_result["entry_price"],
            ))

        signals.sort(key=lambda x: x.edge_pct, reverse=True)
        logger.info(f"{sport_key}: {len(signals)} signals from {len(matched)} matches")
        return signals

    async def compare_all(self) -> list[Signal]:
        all_signals = []

        # Outright markets
        for sport_key in CFG.OUTRIGHT_MARKETS:
            try:
                sigs = await self.compare_outright(sport_key)
                all_signals.extend(sigs)
            except Exception as e:
                logger.error(f"Outright error {sport_key}: {e}", exc_info=True)
            await asyncio.sleep(0.5)

        return all_signals
