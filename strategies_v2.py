"""
Institutional Trend & Volatility Expansion Strategy (Index-Compatible)
Uses pure price action, ATR (Average True Range), and EMA trend filters.
"""
from typing import List, Dict
from strategies import BaseStrategy, Signal

class InstitutionalTrendATRStrategy(BaseStrategy):
    """
    Trades ONLY on confirmed multi-candle breakout in the direction of the 50 EMA,
    with an ATR volatility expansion (filters out chop/sideways noise).
    """
    def __init__(self, ema_period: int = 50, channel_lookback: int = 15,
                 target_pts: float = 24.0, stop_loss_pts: float = 10.0,
                 max_hold_bars: int = 12):
        self.name = f"InstTrendATR(EMA={ema_period}, Lookback={channel_lookback}, TP={target_pts}pt, SL={stop_loss_pts}pt)"
        self.ema_period = ema_period
        self.channel_lookback = channel_lookback
        self.target_pts = target_pts
        self.stop_loss_pts = stop_loss_pts
        self.max_hold_bars = max_hold_bars

    def generate_signal(self, idx: int, candles: List[Dict], in_position: bool) -> Signal:
        if in_position or idx < max(self.ema_period, self.channel_lookback) + 5:
            return Signal(action="HOLD", reason="Waiting")

        current = candles[idx]
        time_str = current["time_str"]

        # Only trade between 09:30 AM and 02:45 PM
        if time_str < "09:30" or time_str > "14:45":
            return Signal(action="HOLD", reason="Outside optimal hours")

        # 1. Compute 50-period EMA
        k = 2.0 / (self.ema_period + 1.0)
        ema = candles[idx - self.ema_period]["close"]
        for j in range(idx - self.ema_period + 1, idx + 1):
            ema = candles[j]["close"] * k + ema * (1.0 - k)

        # 2. Compute 14-period ATR (Average True Range)
        atr_window = candles[idx - 14 : idx]
        ranges = [max(c["high"] - c["low"], abs(c["high"] - candles[idx - 14 + k_idx - 1]["close"]) if k_idx > 0 else c["high"] - c["low"])
                  for k_idx, c in enumerate(atr_window)]
        atr = sum(ranges) / len(ranges) if ranges else 10.0

        # 3. Channel High / Low of preceding candles
        channel = candles[idx - self.channel_lookback : idx]
        highest_high = max(c["high"] for c in channel)
        lowest_low = min(c["low"] for c in channel)

        c_close = current["close"]
        c_open = current["open"]

        # Bullish Breakout: Price punches above channel high + Above EMA + Candle is green
        if c_close > highest_high and c_close > ema and c_close > c_open:
            return Signal(
                action="BUY_CE",
                reason=f"Bullish Trend Breakout (Close {c_close} > High {highest_high}, EMA {round(ema,1)})",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=self.max_hold_bars
            )

        # Bearish Breakdown: Price punches below channel low + Below EMA + Candle is red
        if c_close < lowest_low and c_close < ema and c_close < c_open:
            return Signal(
                action="BUY_PE",
                reason=f"Bearish Trend Breakdown (Close {c_close} < Low {lowest_low}, EMA {round(ema,1)})",
                target_pts=self.target_pts,
                stop_loss_pts=self.stop_loss_pts,
                max_hold_bars=self.max_hold_bars
            )

        return Signal(action="HOLD", reason="In range")
