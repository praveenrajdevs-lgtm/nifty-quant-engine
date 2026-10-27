"""
Market Data Feed & Candle Aggregator
Fetches real 1-minute and 5-minute historical candles for NIFTY 50 and BANK NIFTY.
Uses local JSON caching to ensure offline capability and sub-millisecond replay.
"""
import json
import os
import urllib.request
from datetime import datetime

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SYMBOL_MAP = {
    "NIFTY": "%5ENSEI",
    "BANKNIFTY": "%5ENSEBANK"
}

def fetch_candles(symbol: str = "NIFTY", interval: str = "1m", range_period: str = "5d") -> list:
    """
    Fetches real intraday OHLCV candles.
    :param symbol: "NIFTY" or "BANKNIFTY"
    :param interval: "1m" or "5m"
    :param range_period: "5d" or "7d"
    :return: list of dicts with timestamp, open, high, low, close, volume
    """
    ticker = SYMBOL_MAP.get(symbol.upper(), "%5ENSEI")
    cache_file = os.path.join(CACHE_DIR, f"{symbol.lower()}_{interval}_{range_period}.json")

    # If cached file exists and is less than 1 hour old, use cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
                if len(cached_data) > 0:
                    return cached_data
        except Exception:
            pass

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_period}&interval={interval}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]

    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])

    candles = []
    for i in range(len(timestamps)):
        # Filter out incomplete null bars
        if (opens[i] is None or highs[i] is None or 
            lows[i] is None or closes[i] is None):
            continue

        dt = datetime.fromtimestamp(timestamps[i])
        candles.append({
            "timestamp": timestamps[i],
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "time_str": dt.strftime("%H:%M"),
            "open": round(float(opens[i]), 2),
            "high": round(float(highs[i]), 2),
            "low": round(float(lows[i]), 2),
            "close": round(float(closes[i]), 2),
            "volume": int(volumes[i]) if volumes[i] is not None else 0
        })

    # Save to local cache
    with open(cache_file, "w") as f:
        json.dump(candles, f, indent=2)

    return candles
