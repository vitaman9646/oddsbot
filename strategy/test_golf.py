import asyncio, aiohttp, re, json, sys
sys.path.insert(0, '/app')

async def test_golf():
    async with aiohttp.ClientSession() as s:
        from strategy.odds_fetcher import OddsFetcher
        from strategy.matcher import match_teams_bulk, get_unmatched_report

        f = OddsFetcher(s)
        odds = await f.fetch_outright('golf_masters_tournament_winner')
        bk_teams = {o.team_name: o for o in odds}
        print(f'Bookmaker players: {len(bk_teams)}')
        for o in odds[:10]:
            print(f'  {o.team_name:30s} {o.fair_prob:5.1%} ({o.num_books} books)')

        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        async with s.get('https://gamma-api.polymarket.com/events',
            params={'active':'true','closed':'false','limit':'500'},
            headers=headers) as r:
            events = await r.json()

        pm_players = {}
        for e in events:
            if 'Masters' not in e.get('title','') or 'Winner' not in e.get('title',''):
                continue
            print(f'\nPM Event: {e.get("title")}')
            for m in e.get('markets',[]):
                match = re.search(r'Will (?:the )?(.+?) win', m.get('question',''), re.IGNORECASE)
                if match:
                    player = match.group(1).strip()
                    try:
                        pm_players[player] = float(json.loads(m.get('outcomePrices','[]'))[0])
                    except:
                        pm_players[player] = 0
            break

        print(f'PM players: {len(pm_players)}')
        for name, price in sorted(pm_players.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f'  {name:30s} {price:5.1%}')

        matched = match_teams_bulk(list(bk_teams.keys()), list(pm_players.keys()))

        signals = sorted([
            (bk_name, bk_teams[bk_name].fair_prob, pm_players.get(r.polymarket_name,0), r, bk_teams[bk_name].num_books)
            for bk_name, r in matched.items()
            if abs(bk_teams[bk_name].fair_prob - pm_players.get(r.polymarket_name,0)) > 0.02
        ], key=lambda x: abs(x[1]-x[2]), reverse=True)

        print(f'\nSIGNALS (spread > 2%):')
        for name, bk, pm, res, nb in signals[:20]:
            sp = bk - pm
            warn = '⚠️' if res.method == 'fuzzy' or nb < 3 else '  '
            print(f'  {warn} {"YES" if sp>0 else "NO":3s} {name:25s} BK:{bk:5.1%} PM:{pm:5.1%} D={sp:+5.1%} ({nb}bk, {res.method})')

        print(get_unmatched_report(list(bk_teams.keys()), list(pm_players.keys()), matched))

asyncio.run(test_golf())
