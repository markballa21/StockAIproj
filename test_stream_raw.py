import asyncio
from alpaca.data.live.stock import StockDataStream
from alpaca.data.enums import DataFeed
from config import Config

config = Config()

async def bar_handler(bar):
    print(f"🔥 נר התקבל בזמן אמת! טיקר: {bar.symbol} | שעה: {bar.timestamp} | סגירה: {bar.close}")

stream = StockDataStream(
    api_key=config.ALPACA_KEY,
    secret_key=config.ALPACA_SECRET,
    feed=DataFeed.IEX
)

print("📡 מתחבר ובודק קבלת נרות מ-SPY ו-NVDA...")
stream.subscribe_bars(bar_handler, "NVDA", "SPY")
stream.run()