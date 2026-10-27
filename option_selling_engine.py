"""
Institutional Non-Directional Option Selling Engine (P.R. Sundar / Prop Desk Model)
Simulates Intraday Hedged Short Straddle / Strangle (09:25 AM Entry to 15:15 PM Exit)
with Individual Leg Stop-Losses (25%) and Black-Scholes Intraday Theta Decay.
"""
from typing import List, Dict
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs
from data_feed import fetch_candles

LOT_SIZE = 25  # Nifty lot size

def run_short_straddle_backtest(candles: List[Dict], leg_sl_pct: float = 0.25,
                                target_profit_pct: float = 0.50) -> dict:
    """
    Backtests the classic institutional 09:25 AM Short Straddle on NIFTY:
    - At 09:25 AM, sell 1 lot ATM CE and 1 lot ATM PE.
    - Buy protective wings (+200 pts OTM CE and -200 pts OTM PE) for risk capping & margin relief.
    - Stop loss: +25% on either short leg.
    - Profit target: 50% combined decay.
    - Time exit: 15:15 PM intraday square-off.
    """
    # Group candles by day
    days = {}
    for c in candles:
        day_str = c["datetime"][:10]
        if day_str not in days:
            days[day_str] = []
        days[day_str].append(c)

    daily_trades = []
    base_tte_years = 2.0 / 365.0  # ~2 days to expiry average

    for day_str, day_candles in sorted(days.items()):
        # Find 09:25 candle
        entry_idx = None
        for i, c in enumerate(day_candles):
            if c["time_str"] >= "09:25":
                entry_idx = i
                break

        if entry_idx is None or entry_idx >= len(day_candles) - 5:
            continue

        entry_candle = day_candles[entry_idx]
        spot_entry = entry_candle["close"]
        atm_strike = get_atm_strike(spot_entry, step=50)

        # Price the ATM options at entry
        ce_entry = calculate_option_price(spot_entry, atm_strike, base_tte_years, option_type="CE")["price"]
        pe_entry = calculate_option_price(spot_entry, atm_strike, base_tte_years, option_type="PE")["price"]

        # Hedges: 200 pts OTM wings bought
        wing_ce_entry = calculate_option_price(spot_entry, atm_strike + 200, base_tte_years, option_type="CE")["price"]
        wing_pe_entry = calculate_option_price(spot_entry, atm_strike - 200, base_tte_years, option_type="PE")["price"]

        # Active state
        ce_active = True
        pe_active = True
        ce_exit_price = None
        pe_exit_price = None
        ce_exit_time = None
        pe_exit_time = None
        exit_reason_ce = ""
        exit_reason_pe = ""

        ce_sl = ce_entry * (1.0 + leg_sl_pct)
        pe_sl = pe_entry * (1.0 + leg_sl_pct)

        # Simulate through the rest of the day until 15:15
        for j in range(entry_idx + 1, len(day_candles)):
            c = day_candles[j]
            current_spot = c["close"]
            time_str = c["time_str"]

            # Compute remaining time to expiry (intraday theta decay fraction)
            bars_held = j - entry_idx
            current_tte = max(0.0001, base_tte_years - (bars_held / (75.0 * 365.0)))

            curr_ce = calculate_option_price(current_spot, atm_strike, current_tte, option_type="CE")["price"]
            curr_pe = calculate_option_price(current_spot, atm_strike, current_tte, option_type="PE")["price"]

            # Check CE Stop Loss
            if ce_active and curr_ce >= ce_sl:
                ce_active = False
                ce_exit_price = curr_ce
                ce_exit_time = c["datetime"]
                exit_reason_ce = f"CE Stop Loss (+{leg_sl_pct*100:.0f}%)"

            # Check PE Stop Loss
            if pe_active and curr_pe >= pe_sl:
                pe_active = False
                pe_exit_price = curr_pe
                pe_exit_time = c["datetime"]
                exit_reason_pe = f"PE Stop Loss (+{leg_sl_pct*100:.0f}%)"

            # EOD square-off at 15:15
            if time_str >= "15:15":
                if ce_active:
                    ce_active = False
                    ce_exit_price = curr_ce
                    ce_exit_time = c["datetime"]
                    exit_reason_ce = "EOD Square-Off (Theta Decay Captured)"
                if pe_active:
                    pe_active = False
                    pe_exit_price = curr_pe
                    pe_exit_time = c["datetime"]
                    exit_reason_pe = "EOD Square-Off (Theta Decay Captured)"
                break

        # Fallback if market ended before 15:15
        if ce_active:
            ce_exit_price = curr_ce
            ce_exit_time = day_candles[-1]["datetime"]
            exit_reason_ce = "Session End"
        if pe_active:
            pe_exit_price = curr_pe
            pe_exit_time = day_candles[-1]["datetime"]
            exit_reason_pe = "Session End"

        # Calculate PnL for Short CE leg: Sold at ce_entry, Bought back at ce_exit_price
        ce_cost = calculate_option_trade_costs(buy_price=ce_exit_price, sell_price=ce_entry, quantity=LOT_SIZE)
        # Calculate PnL for Short PE leg: Sold at pe_entry, Bought back at pe_exit_price
        pe_cost = calculate_option_trade_costs(buy_price=pe_exit_price, sell_price=pe_entry, quantity=LOT_SIZE)

        # Hedge costs (approximate 30% decay on cheap wings):
        wing_cost = (wing_ce_entry + wing_pe_entry) * 0.30 * LOT_SIZE + 40.0  # ₹40 brokerage

        total_gross = ce_cost["gross_pnl"] + pe_cost["gross_pnl"]
        total_charges = ce_cost["total_charges"] + pe_cost["total_charges"] + wing_cost
        total_net = round(total_gross - total_charges, 2)

        daily_trades.append({
            "date": day_str,
            "strike": atm_strike,
            "spot_entry": spot_entry,
            "ce_entry": ce_entry,
            "ce_exit": ce_exit_price,
            "pe_entry": pe_entry,
            "pe_exit": pe_exit_price,
            "gross_pnl": round(total_gross, 2),
            "charges": round(total_charges, 2),
            "net_pnl": total_net,
            "ce_reason": exit_reason_ce,
            "pe_reason": exit_reason_pe
        })

    # Summary Statistics
    total_days = len(daily_trades)
    winning_days = [d for d in daily_trades if d["net_pnl"] > 0]
    losing_days = [d for d in daily_trades if d["net_pnl"] <= 0]
    win_rate = (len(winning_days) / total_days * 100.0) if total_days > 0 else 0.0

    net_total = sum(d["net_pnl"] for d in daily_trades)
    gross_total = sum(d["gross_pnl"] for d in daily_trades)
    charges_total = sum(d["charges"] for d in daily_trades)

    tot_gain = sum(d["net_pnl"] for d in winning_days)
    tot_loss = abs(sum(d["net_pnl"] for d in losing_days))
    profit_factor = round(tot_gain / tot_loss, 2) if tot_loss > 0 else 99.0

    # Max Drawdown
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for d in daily_trades:
        cum += d["net_pnl"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return {
        "strategy": f"Institutional Short Straddle (SL={leg_sl_pct*100:.0f}%)",
        "total_days": total_days,
        "winning_days": len(winning_days),
        "losing_days": len(losing_days),
        "win_rate_pct": round(win_rate, 1),
        "gross_pnl": round(gross_total, 2),
        "charges": round(charges_total, 2),
        "net_pnl": round(net_total, 2),
        "profit_factor": profit_factor,
        "max_drawdown": round(max_dd, 2),
        "days": daily_trades
    }

if __name__ == "__main__":
    candles = fetch_candles("NIFTY", interval="5m", range_period="60d")
    print(f"Loaded {len(candles)} 5-minute candles across 60 days.\n")

    for sl in [0.20, 0.25, 0.30, 0.35]:
        res = run_short_straddle_backtest(candles, leg_sl_pct=sl)
        print("=" * 80)
        print(f"RESULTS FOR: {res['strategy']}")
        print(f"  • Total Trading Days: {res['total_days']}")
        print(f"  • Winning Days: {res['winning_days']} | Losing Days: {res['losing_days']}")
        print(f"  • WIN RATE: {res['win_rate_pct']}%")
        print(f"  • Gross P&L: ₹{res['gross_pnl']:+,.1f}")
        print(f"  • Brokerage, Taxes & Hedge Cost: ₹{res['charges']:,.1f}")
        print(f"  • NET PROFIT (IN POCKET): ₹{res['net_pnl']:+,.1f}")
        print(f"  • Profit Factor: {res['profit_factor']}")
        print(f"  • Max Drawdown: ₹{res['max_drawdown']:,.1f}")
