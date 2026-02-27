
import sys, asyncio, aiohttp, re
sys.path.insert(0, "/app")

async def check():
    async with aiohttp.ClientSession() as s:
        async with s.get("https://gamma-api.polymarket.com/events",
            params={"active":"true","closed":"false","limit":"500"},
            headers={"User-Agent":"Mozilla/5.0"}) as r:
            events = await r.json()
        for e in events:
            if "Masters" not in e.get("title","") or "Winner" not in e.get("title",""):
                continue
            search = ["gotterup","si woo","spaun","noren","griffin","english","bridgeman","penge","mccarty","fox"]
            for m in e.get("markets",[]):
                match = re.search(r"Will (?:the )?(.+?) win", m.get("question",""), re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    if any(x in name.lower() for x in search):
                        print(name)
            break

asyncio.run(check())
