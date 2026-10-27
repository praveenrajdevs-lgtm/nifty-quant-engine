"""
Adaptive Institutional Straddle Engine with Regime/Shock Filter
Skips entering on violent gap/shock days (opening 10-min candle > 80 pts).
"""
from typing import List, Dict
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs
from data_feed import fetch_candles

LOT_SIZE = 25

def run_adaptive_straddle(candles: List[Dict], leg_sl_pct: float = 0.30,
                          max_open_range_pts: float = 75.0) -> dict:
    days = {}
    for c in candles:
        day_str = c["datetime"][:10]
        if day_str not in days:
            days[day_str] = []
        days[day_str].append(c)

    daily_trades = []
    base_tte_years = 2.0 / 365.0

    for day_str, day_candles in sorted(days.items()):
        # Find 09:25 candle
        entry_idx = None
        for i, c in enumerate(day_candles):
            if c["time_str"] >= "09:25":
                entry_idx = i
                break

        if entry_idx is None or entry_idx >= len(day_candles) - 5:
            continue

        # REGIME FILTER: Check opening 10-minute volatility (09:15 to 09:25)
        open_candles = day_candles[:entry_idx]
        open_high = max(c["high"] for c in open_candles)
        open_low = min(c["low"] for c in open_candles)
        open_range = open_high - open_low

        # If opening 10 minutes is a violent shock day (> max_open_range_pts), SKIP option selling!
        if open_range > max_open_range_pts:
            continue

        entry_candle = day_candles[entry_idx]
        spot_entry = entry_candle["close"]
        atm_strike = get_atm_strike(spot_entry, step=50)

        ce_entry = calculate_option_price(spot_entry, atm_strike, base_tte_years, option_type="CE")["price"]
        pe_entry = calculate_option_price(spot_entry, atm_strike, base_tte_years, option_type="PE")["price"]

        wing_ce_entry = calculate_option_price(spot_entry, atm_strike + 200, base_tte_years, option_type="CE")["price"]
        wing_pe_entry = calculate_option_price(spot_entry, atm_strike - 200, base_tte_years, option_type="PE")["price"]

        ce_active = True
        pe_active = True
        ce_exit_price = None
        pe_exit_price = None
        ce_sl = ce_entry * (1.0 + leg_sl_pct)
        pe_sl = pe_entry * (1.0 + leg_sl_pct)

        for j in range(entry_idx + 1, len(day_candles)):
            c = day_candles[j]
            current_spot = c["close"]
            time_str = c["time_str"]

            bars_held = j - entry_idx
            current_tte = max(0.0001, base_tte_years - (bars_held / (75.0 * 365.0)))

            curr_ce = calculate_option_price(current_spot, atm_strike, current_tte, option_type="CE")["price"]
            curr_pe = calculate_option_price(current_spot, atm_strike, current_tte, option_type="PE")["price"]

            if ce_active and curr_ce >= ce_sl:
                ce_active = False
                ce_exit_price = curr_ce

            if pe_active and curr_pe >= pe_sl:
                pe_active = False
                pe_exit_price = curr_pe

            if time_str >= "15:15":
                if ce_active:
                    ce_active = False
                    ce_exit_price = curr_ce
                if pe_active:
                    pe_active = False
                    pe_exit_price = curr_pe
                break

        if ce_active:
            ce_exit_price = curr_ce
        if pe_active:
            pe_exit_price = curr_pe

        ce_cost = calculate_option_trade_costs(buy_price=ce_exit_price, sell_price=ce_entry, quantity=LOT_SIZE)
        pe_cost = calculate_option_trade_costs(buy_price=pe_exit_price, sell_price=pe_entry, quantity=LOT_SIZE)
        wing_cost = (wing_ce_entry + wing_pe_entry) * 0.30 * LOT_SIZE + 40.0

        total_gross = ce_cost["gross_pnl"] + pe_cost["gross_pnl"]
        total_charges = ce_cost["total_charges"] + pe_cost["total_charges"] + wing_cost
        total_net = round(total_gross - total_charges, 2)

        daily_trades.append({
            "date": day_str,
            "net_pnl": total_net,
            "gross_pnl": round(total_gross, 2),
            "charges": round(total_charges, 2)
        })

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
        "total_days": total_days,
        "winning_days": len(winning_days),
        "losing_days": len(losing_days),
        "win_rate_pct": round(win_rate, 1),
        "gross_pnl": round(gross_total, 2),
        "charges": round(charges_total, 2),
        "net_pnl": round(net_total, 2),
        "profit_factor": profit_factor,
        "max_drawdown": round(max_dd, 2)
    }

if __name__ == "__main__":
    candles = fetch_candles("NIFTY", interval="5m", range_period="60d")
    for shock_threshold in [60.0, 75.0, 90.0, 120.0]:
        res = run_adaptive_straddle(candles, leg_sl_pct=0.30, max_open_range_pts=shock_threshold)
        print("=" * 80)
        print(f"ADAPTIVE STRADDLE (Skip Opening Shock > {shock_threshold} pts)")
        print(f"  • Days Traded: {res['total_days']}")
        print(f"  • Winning Days: {res['winning_days']} | Losing Days: {res['losing_days']}")
        print(f"  • WIN RATE: {res['win_rate_pct']}%")
        print(f"  • Net Profit: ₹{res['net_pnl']:+,.1f}")
        print(f"  • Profit Factor: {res['profit_factor']}")
        print(f"  • Max Drawdown: ₹{res['max_drawdown']:,.1f}")
