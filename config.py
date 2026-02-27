import os

class Config:
    # Telegram
    TELEGRAM_TOKEN: str = os.getenv("ARB_TG_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("ARB_TG_CHAT", "")

    # The Odds API
    ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")
    ODDS_API_BASE: str = "https://api.the-odds-api.com/v4"

    # Polymarket
    GAMMA_EVENTS_API: str = "https://gamma-api.polymarket.com/events"
    CLOB_API: str = "https://clob.polymarket.com"

    # Strategy
    MIN_EDGE_PCT: float = float(os.getenv("MIN_EDGE_PCT", "8.0"))
    MIN_VOLUME_USD: float = float(os.getenv("MIN_VOLUME_USD", "500.0"))
    MAX_DAYS_TO_EXPIRY: int = int(os.getenv("MAX_DAYS_TO_EXPIRY", "14"))
    POSITION_SIZE_USD: float = float(os.getenv("POSITION_SIZE_USD", "5.0"))
    SCAN_INTERVAL: int = int(os.getenv("SCAN_INTERVAL", "3600"))

    # Sports to monitor
    SPORTS: list = [
        "soccer_epl",
        "soccer_uefa_champs_league",
        "basketball_nba",
        "soccer_spain_la_liga",
    ]

    # Files
    TRADES_FILE: str = "data/trades.jsonl"
    LOG_FILE: str = "logs/bot.log"

CFG = Config()
