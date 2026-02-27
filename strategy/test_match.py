
import asyncio, aiohttp, re, json
from strategy.odds_fetcher import OddsFetcher
from strategy.matcher import match_teams_bulk, get_unmatched_report

DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

def extract_team(question):
    import re
    match = re.search(r"Will (?:the )?(.+?) win", question, re.IGNORECASE)
    return match.group(1).strip() if match else None

async def test():
    async with aiohttp.ClientSession() as s:
        f = OddsFetcher(s)
        odds = await f.fetch_outright("basketball_nba_championship_winner")
        bk_teams = [o.team_name for o in odds]

        async with s.get("https://gamma-api.polymarket.com/events",
            params={"active":"true","closed":"false","limit":"200"},
            headers=DEFAULT_HEADERS) as r:
            events = await r.json()

        pm_teams = []
        pm_prices = {}
        for e in events:
            if "NBA" not in e.get("title","") or "Champion" not in e.get("title",""):
                continue
            print(f"EVENT: {e.get('title')}")
            for m in e.get("markets",[]):
                team = extract_team(m.get("question",""))
                if team:
                    pm_teams.append(team)
                    try:
                        prices = json.loads(m.get("outcomePrices","[]"))
                        pm_prices[team] = float(prices[0])
                        print(f"  {team:30s} {float(prices[0]):6.1%}")
                    except:
                        pass
            break

        matched = match_teams_bulk(bk_teams, pm_teams)
        print("MATCHING:")
        for bk_name, result in sorted(matched.items(), key=lambda x: x[1].confidence, reverse=True):
            bk_prob = next(o.fair_prob for o in odds if o.team_name == bk_name)
            pm_price = pm_prices.get(result.polymarket_name, 0)
            spread = bk_prob - pm_price
            signal = "BUY YES" if spread > 0.08 else ("BUY NO" if spread < -0.08 else "")
            print(f"  {result.method:8s} ({result.confidence:.2f}) {bk_name:25s} BK:{bk_prob:5.1%} PM:{pm_price:5.1%} D={spread:+5.1%} {signal}")

        print(get_unmatched_report(bk_teams, pm_teams, matched))

asyncio.run(test())
