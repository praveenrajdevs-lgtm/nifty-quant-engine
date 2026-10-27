"""
Modular Trading Strategies for Indian Index Options Scalping
Includes:
1. DemandSupplyReversalStrategy (User's intuitive support/demand bounce)
2. VWAPBounceStrategy (Institutional intraday mean-reversion)
3. MomentumBreakoutStrategy (High-volatility trend continuation)
"""
from dataclasses import dataclass
from typing import Optional, List, Dict

@dataclass
class Signal:
    action: str  # "BUY_CE", "BUY_PE", "EXIT", "HOLD"
    reason: str
    target_pts: float = 16.0    # ~₹400 on 25 lot
    stop_loss_pts: float = 8.0  # ~₹200 on 25 lot
    max_hold_bars: int = 15     # Exit after 15 bars if neither target nor stop hit (avoids theta death)

class BaseStrategy:
    name: str = "BaseStrategy"

    def generate_signal(self, idx: int, candles: List[Dict], in_position: bool) -> Signal:
        raise NotImplementedError

class DemandSupplyReversalStrategy(BaseStrategy):
    """
    Identifies institutional Demand Zones (support) and Supply Zones (resistance).
    Enters ATM Call/Put when price rejects the level with a reversal wick (pinbar/hammer).
    """
    def __init__(self, lookback: int = 25, wick_threshold: float = 0.35, 
                 target_pts: float = 16.0, stop_loss_pts: float = 10.0, max_hold_bars: int = 12):
        self.name = f"DemandSupplyReversal(lookback={lookback}, TP={target_pts}pt, SL={stop_loss_pts}pt)"
        self.lookback = lookback
        self.wick_threshold = wick_threshold
        self.target_pts = target_pts
        self.stop_loss_pts = stop_loss_pts
        self.max_hold_bars = max_hold_bars

    def generate_signal(self, idx: int, candles: List[Dict], in_position: bool) -> Signal:
        if in_position or idx < self.lookback:
            return Signal(action="HOLD", reason="Waiting")

        current = candles[idx]
        window = candles[idx - self.lookback : idx]

        demand_level = min(c["low"] for c in window)
        supply_level = max(c["high"] for c in window)

        c_open = current["open"]
        c_close = current["close"]
        c_high = current["high"]
        c_low = current["low"]
        candle_range = max(c_high - c_low, 0.1)

        # Bullish Reversal: Price swept into Demand Zone, but buyers rejected lower prices
        lower_wick = min(c_open, c_close) - c_low
        is_bullish_hammer = (lower_wick / candle_range) >= self.wick_threshold and c_close >= c_open

        if c_low <= demand_level * 1.001 and is_bullish_hammer:
            return Signal(
                action="BUY_CE",
                reason=f"Demand Zone Reversal (Low: {c_low} near {demand_level})",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=self.max_hold_bars
            )

        # Bearish Reversal: Price tested Supply Zone, but sellers pushed it down
        upper_wick = c_high - max(c_open, c_close)
        is_shooting_star = (upper_wick / candle_range) >= self.wick_threshold and c_close <= c_open

        if c_high >= supply_level * 0.999 and is_shooting_star:
            return Signal(
                action="BUY_PE",
                reason=f"Supply Zone Reversal (High: {c_high} near {supply_level})",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=self.max_hold_bars
            )

        return Signal(action="HOLD", reason="No setup")

class VWAPBounceStrategy(BaseStrategy):
    """
    Intraday Volume-Weighted Average Price (VWAP) Mean Reversion.
    Enters when price is extended away from VWAP and starts curling back.
    """
    def __init__(self, deviation_pct: float = 0.25, target_pts: float = 16.0, stop_loss_pts: float = 8.0):
        self.name = f"VWAP_MeanReversion(dev={deviation_pct}%, TP={target_pts}pt, SL={stop_loss_pts}pt)"
        self.deviation_pct = deviation_pct
        self.target_pts = target_pts
        self.stop_loss_pts = stop_loss_pts

    def generate_signal(self, idx: int, candles: List[Dict], in_position: bool) -> Signal:
        if in_position or idx < 20:
            return Signal(action="HOLD", reason="Waiting")

        # Compute rolling intraday VWAP for last 30 bars
        window = candles[max(0, idx - 30) : idx + 1]
        vol_sum = sum(c["volume"] for c in window)
        if vol_sum == 0:
            return Signal(action="HOLD", reason="Zero volume")

        vwap = sum(((c["high"] + c["low"] + c["close"]) / 3.0) * c["volume"] for c in window) / vol_sum
        current_close = candles[idx]["close"]
        prev_close = candles[idx - 1]["close"]

        # Oversold bounce towards VWAP
        if current_close < vwap * (1.0 - self.deviation_pct / 100.0) and current_close > prev_close:
            return Signal(
                action="BUY_CE",
                reason=f"VWAP Oversold Bounce (Price: {current_close}, VWAP: {round(vwap, 1)})",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=10
            )

        # Overbought rejection towards VWAP
        if current_close > vwap * (1.0 + self.deviation_pct / 100.0) and current_close < prev_close:
            return Signal(
                action="BUY_PE",
                reason=f"VWAP Overbought Rejection (Price: {current_close}, VWAP: {round(vwap, 1)})",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=10
            )

        return Signal(action="HOLD", reason="Near VWAP")


class FilteredKeyLevelStrategy(BaseStrategy):
    """
    Institutional Discipline Strategy:
    1. Maximum 2 trades per day (prevents overtrading & commission bleed).
    2. Higher timeframe key level lookback (60-minute window for real demand/supply).
    3. Time filter: Trades only between 09:30 AM and 02:30 PM.
    4. Asymmetric Risk-Reward: Target 20 points (₹500), Stop Loss 9 points (₹225).
    """
    def __init__(self, lookback: int = 60, target_pts: float = 20.0, stop_loss_pts: float = 9.0,
                 max_trades_per_day: int = 2):
        self.name = f"FilteredKeyLevel(lookback={lookback}, TP={target_pts}pt, SL={stop_loss_pts}pt, MaxDaily={max_trades_per_day})"
        self.lookback = lookback
        self.target_pts = target_pts
        self.stop_loss_pts = stop_loss_pts
        self.max_trades_per_day = max_trades_per_day
        self.daily_trade_count = {}

    def generate_signal(self, idx: int, candles: List[Dict], in_position: bool) -> Signal:
        if in_position or idx < self.lookback:
            return Signal(action="HOLD", reason="Waiting")

        current = candles[idx]
        current_date = current["datetime"][:10]
        time_str = current["time_str"]

        # 1. Trading time window: 09:30 to 14:30
        if time_str < "09:30" or time_str > "14:30":
            return Signal(action="HOLD", reason="Outside trading hours")

        # 2. Daily trade count filter
        today_trades = self.daily_trade_count.get(current_date, 0)
        if today_trades >= self.max_trades_per_day:
            return Signal(action="HOLD", reason="Max daily trades reached")

        window = candles[idx - self.lookback : idx]
        demand_level = min(c["low"] for c in window)
        supply_level = max(c["high"] for c in window)

        c_open = current["open"]
        c_close = current["close"]
        c_high = current["high"]
        c_low = current["low"]
        candle_range = max(c_high - c_low, 0.1)

        # Bullish rejection at major demand level
        lower_wick = min(c_open, c_close) - c_low
        is_bullish_hammer = (lower_wick / candle_range) >= 0.40 and c_close > c_open

        if c_low <= demand_level * 1.0005 and is_bullish_hammer:
            self.daily_trade_count[current_date] = today_trades + 1
            return Signal(
                action="BUY_CE",
                reason=f"Major Demand Rejection at {demand_level}",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=18
            )

        # Bearish rejection at major supply level
        upper_wick = c_high - max(c_open, c_close)
        is_shooting_star = (upper_wick / candle_range) >= 0.40 and c_close < c_open

        if c_high >= supply_level * 0.9995 and is_shooting_star:
            self.daily_trade_count[current_date] = today_trades + 1
            return Signal(
                action="BUY_PE",
                reason=f"Major Supply Rejection at {supply_level}",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=18
            )

        return Signal(action="HOLD", reason="No key level signal")

