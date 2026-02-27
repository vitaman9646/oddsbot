import asyncio, aiohttp, re, json, sys
sys.path.insert(0, "/app")
from strategy.odds_fetcher import OddsFetcher, OUTRIGHT_SPORTS
from strategy.matcher import match_teams_bulk

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

PM_KEYWORDS = {
    "basketball_nba_championship_winner": ["NBA", "Champion"],
    "icehockey_nhl_championship_winner": ["NHL", "Stanley Cup"],
    "golf_masters_tournament_winner": ["Masters"],
    "soccer_fifa_world_cup_winner": ["FIFA", "World Cup"],
}

async def test():
    async with aiohttp.ClientSession() as s:
        f = OddsFetcher(s)
        async with s.get("https://gamma-api.polymarket.com/events",
            params={"active":"true","closed":"false","limit":"500"},
            headers=HEADERS) as r:
            events = await r.json()

        for sport_key, keywords in PM_KEYWORDS.items():
            print(f"\n{'='*60}\n{OUTRIGHT_SPORTS[sport_key]}\n{'='*60}")
            odds = await f.fetch_outright(sport_key)
            if not odds:
                print("  No bookmaker data")
                continue

            bk_teams = {o.team_name: o for o in odds}
            pm_event = next((e for e in events if all(k.lower() in e.get("title","").lower() for k in keywords)), None)
            if not pm_event:
                print(f"  No PM event found for {keywords}")
                continue

            print(f"  PM: {pm_event.get('title')}")
            pm_teams = {}
            for m in pm_event.get("markets", []):
                match = re.search(r"Will (?:the )?(.+?) win", m.get("question",""), re.IGNORECASE)
                if match:
                    team = match.group(1).strip()
                    try:
                        pm_teams[team] = float(json.loads(m.get("outcomePrices","[]"))[0])
                    except:
                        pass

            matched = match_teams_bulk(list(bk_teams.keys()), list(pm_teams.keys()))
            print(f"  Matched: {len(matched)}/{len(bk_teams)}")

            signals = sorted([
                (bk_name, bk_teams[bk_name].fair_prob, pm_teams.get(r.polymarket_name, 0), r)
                for bk_name, r in matched.items()
                if abs(bk_teams[bk_name].fair_prob - pm_teams.get(r.polymarket_name, 0)) > 0.03
            ], key=lambda x: abs(x[1]-x[2]), reverse=True)

            if signals:
                for name, bk, pm, r in signals[:10]:
                    sp = bk - pm
                    print(f"  {'YES' if sp>0 else 'NO ':3s} {name:30s} BK:{bk:5.1%} PM:{pm:5.1%} D={sp:+5.1%}")
            else:
                print("  No spreads > 3%")
            await asyncio.sleep(0.5)

asyncio.run(test())
