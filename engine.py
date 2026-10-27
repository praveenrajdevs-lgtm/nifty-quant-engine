"""
Simulation & Backtest Engine for Indian Index Options
Simulates dynamic Black-Scholes option prices, bid-ask slippage, and SEBI/Zerodha fees.
"""
from typing import List, Dict
from dataclasses import dataclass
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs
from strategies import BaseStrategy

LOT_SIZES = {
    "NIFTY": 25,
    "BANKNIFTY": 15
}

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100
}

@dataclass
class TradeRecord:
    entry_time: str
    exit_time: str
    symbol: str
    option_type: str
    strike: int
    entry_spot: float
    exit_spot: float
    entry_premium: float
    exit_premium: float
    quantity: int
    gross_pnl: float
    charges: float
    net_pnl: float
    exit_reason: str
    bars_held: int

def run_backtest(strategy: BaseStrategy, candles: List[Dict], symbol: str = "NIFTY",
                 slippage_pts: float = 0.5) -> dict:
    """
    Executes a backtest on historical intraday candles.
    """
    lot_size = LOT_SIZES.get(symbol.upper(), 25)
    strike_step = STRIKE_STEPS.get(symbol.upper(), 50)
    
    trades: List[TradeRecord] = []
    active_trade = None

    # Time to expiry assumption: 2 days (average weekly expiry distance)
    base_tte_years = 2.0 / 365.0

    for i in range(len(candles)):
        current = candles[i]
        spot = current["close"]

        # Check existing active trade
        if active_trade is not None:
            active_trade["bars_held"] += 1
            entry_prem = active_trade["entry_premium"]
            target_pts = active_trade["target_pts"]
            sl_pts = active_trade["stop_loss_pts"]
            max_bars = active_trade["max_bars"]

            # Compute current option price with simulated theta decay over holding period
            tte = max(0.0001, base_tte_years - (active_trade["bars_held"] / (375.0 * 365.0)))
            opt_data = calculate_option_price(
                spot=spot,
                strike=active_trade["strike"],
                time_to_expiry_years=tte,
                option_type=active_trade["option_type"]
            )
            current_premium = opt_data["price"]
            pts_change = current_premium - entry_prem

            exit_reason = None
            if pts_change >= target_pts:
                exit_reason = f"TARGET HIT (+{round(pts_change, 1)} pts)"
            elif pts_change <= -sl_pts:
                exit_reason = f"STOP LOSS HIT ({round(pts_change, 1)} pts)"
            elif active_trade["bars_held"] >= max_bars:
                exit_reason = f"TIME STOP ({round(pts_change, 1)} pts)"

            if exit_reason is not None:
                # Apply slippage on exit
                exit_premium = round(max(0.5, current_premium - slippage_pts), 2)
                cost_summary = calculate_option_trade_costs(
                    buy_price=active_trade["entry_premium"],
                    sell_price=exit_premium,
                    quantity=lot_size
                )

                trades.append(TradeRecord(
                    entry_time=active_trade["entry_time"],
                    exit_time=current["datetime"],
                    symbol=symbol,
                    option_type=active_trade["option_type"],
                    strike=active_trade["strike"],
                    entry_spot=active_trade["entry_spot"],
                    exit_spot=spot,
                    entry_premium=active_trade["entry_premium"],
                    exit_premium=exit_premium,
                    quantity=lot_size,
                    gross_pnl=cost_summary["gross_pnl"],
                    charges=cost_summary["total_charges"],
                    net_pnl=cost_summary["net_pnl"],
                    exit_reason=exit_reason,
                    bars_held=active_trade["bars_held"]
                ))
                active_trade = None
                continue

        # Check for new entry signal
        signal = strategy.generate_signal(i, candles, in_position=(active_trade is not None))
        if signal.action in ["BUY_CE", "BUY_PE"]:
            opt_type = "CE" if signal.action == "BUY_CE" else "PE"
            strike = get_atm_strike(spot, step=strike_step)
            
            # Initial option pricing
            opt_data = calculate_option_price(
                spot=spot,
                strike=strike,
                time_to_expiry_years=base_tte_years,
                option_type=opt_type
            )
            # Add slippage on entry (buy slightly higher)
            entry_premium = round(opt_data["price"] + slippage_pts, 2)

            active_trade = {
                "entry_time": current["datetime"],
                "option_type": opt_type,
                "strike": strike,
                "entry_spot": spot,
                "entry_premium": entry_premium,
                "target_pts": signal.target_pts,
                "stop_loss_pts": signal.stop_loss_pts,
                "max_bars": signal.max_hold_bars,
                "bars_held": 0,
                "reason": signal.reason
            }

    # Aggregate performance statistics
    total_trades = len(trades)
    winning_trades = [t for t in trades if t.net_pnl > 0]
    losing_trades = [t for t in trades if t.net_pnl <= 0]
    
    gross_pnl = sum(t.gross_pnl for t in trades)
    total_charges = sum(t.charges for t in trades)
    net_pnl = sum(t.net_pnl for t in trades)
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    total_gain = sum(t.net_pnl for t in winning_trades)
    total_loss = abs(sum(t.net_pnl for t in losing_trades))
    profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else 0.0

    # Calculate Max Drawdown
    peak = 0.0
    cum_pnl = 0.0
    max_dd = 0.0
    for t in trades:
        cum_pnl += t.net_pnl
        if cum_pnl > peak:
            peak = cum_pnl
        dd = peak - cum_pnl
        if dd > max_dd:
            max_dd = dd

    return {
        "strategy_name": strategy.name,
        "symbol": symbol,
        "total_candles": len(candles),
        "total_trades": total_trades,
        "wins": len(winning_trades),
        "losses": len(losing_trades),
        "win_rate_pct": round(win_rate, 1),
        "gross_pnl": round(gross_pnl, 2),
        "total_charges": round(total_charges, 2),
        "net_pnl": round(net_pnl, 2),
        "profit_factor": profit_factor,
        "max_drawdown": round(max_dd, 2),
        "trades": trades
    }
