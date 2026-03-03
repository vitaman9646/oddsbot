import os


class Config:
    # --- Telegram ---
    TELEGRAM_TOKEN: str = os.getenv("ARB_TG_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("ARB_TG_CHAT", "")

    # --- The Odds API ---
    ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")
    ODDS_API_BASE: str = "https://api.the-odds-api.com/v4"

    # --- Polymarket ---
    GAMMA_EVENTS_API: str = "https://gamma-api.polymarket.com/events"
    CLOB_API: str = "https://clob.polymarket.com"

    # --- Strategy ---
    MIN_EDGE_PCT: float = float(os.getenv("MIN_EDGE_PCT", "3.0"))
    MIN_VOLUME_USD: float = float(os.getenv("MIN_VOLUME_USD", "1000.0"))
    MIN_BOOKS: int = int(os.getenv("MIN_BOOKS", "3"))
    MIN_PM_PRICE: float = float(os.getenv("MIN_PM_PRICE", "0.05"))
    MAX_PM_PRICE: float = float(os.getenv("MAX_PM_PRICE", "0.95"))
    POSITION_SIZE_USD: float = float(os.getenv("POSITION_SIZE_USD", "5.0"))
    SCAN_INTERVAL: int = int(os.getenv("SCAN_INTERVAL", "300"))
    DEDUP_PRICE_THRESHOLD: float = float(os.getenv("DEDUP_THRESHOLD", "0.02"))

    # --- Outright markets: odds-api key → PM search keywords ---
    OUTRIGHT_MARKETS: dict = {
        "basketball_nba_championship_winner": {
            "keywords": ["NBA", "Champion"],
            "display": "NBA Champion",
        },
        "icehockey_nhl_championship_winner": {
            "keywords": ["NHL", "Stanley Cup"],
            "display": "NHL Stanley Cup",
        },
        "golf_masters_tournament_winner": {
            "keywords": ["Masters", "Winner"],
            "display": "The Masters - Winner",
        },
    }

    # --- Game-level markets: odds-api sport keys ---
    # Эти рынки ищутся на PM как отдельные матчи
    GAME_SPORTS: list = [
        "basketball_nba",
        "icehockey_nhl",
        # "soccer_epl",  # раскомментируй когда появятся на PM
    ]

    # --- Files ---
    TRADES_FILE: str = "data/trades.jsonl"
    LOG_FILE: str = "logs/bot.log"


CFG = Config()
