
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

# Ensure environment variables from .env are loaded into runtime
load_dotenv()


@dataclass(frozen=True)
class Config:
    # API Keys & Secrets
    ALPACA_KEY: str = os.getenv("ALPACA_KEY", "")
    ALPACA_SECRET: str = os.getenv("ALPACA_SECRET", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")

    # Model Names
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet")

    # Database & Storage Paths
    DB_PATH: str = os.getenv("DB_PATH", "market_data.db")

    # Execution & Environment Flags
    IS_PAPER: bool = True
    DATA_LIMIT: int = 100

    # Watchlist & Risk Defaults
    WATCHLIST: List[str] = field(
        default_factory=lambda: ["NVDA", "AAPL", "MSFT", "TSLA", "AMD"]
    )
    MAX_OPEN_POSITIONS: int = 3
    MAX_DAILY_LOSSES: int = 2

    def __post_init__(self):
        """Validate critical environment variables on startup."""
        if not self.ALPACA_KEY or not self.ALPACA_SECRET:
            raise ValueError(
                "Missing Alpaca API credentials in environment (.env)!"
            )