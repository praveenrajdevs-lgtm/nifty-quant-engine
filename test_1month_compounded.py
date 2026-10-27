"""
1-Month Real Intraday Compounded Backtest (Starting Capital: ₹50,000)
Evaluates every single trading day over the last 30 days using real intraday data,
compounding lots as capital grows, and deducting exact Zerodha & SEBI taxes.
"""
from datetime import datetime
from data_feed import fetch_candles
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs

LOT_SIZE = 25

def run_1month_compounded(initial_capital: float = 50000.0, capital_per_lot: float = 35000.0, leg_sl_pct: float = 0.30):
    # Fetch 5-minute candles covering the last 30-45 days
    candles = fetch_candles("NIFTY", interval="5m", range_period="60d")
    
    # Filter for the last 22 trading sessions (approx 1 calendar month)
    days_dict = {}
    for c in candles:
        day_str = c["datetime"][:10]
        if day_str not in days_dict:
            days_dict[day_str] = []
        days_dict[day_str].append(c)

    all_days = sorted(days_dict.keys())
    last_month_days = all_days[-22:]  # Last ~22 trading sessions (1 month)

    capital = initial_capital
    peak = initial_capital
    max_dd = 0.0

    daily_results = []
    base_tte = 2.0 / 365.0

    for day_str in last_month_days:
        day_candles = days_dict[day_str]
        dt = datetime.strptime(day_str, "%Y-%m-%d")
        is_expiry = (dt.weekday() == 3)  # Thursday

        # Dynamic lot sizing: at ₹50,000 -> 1 lot; at ₹70,000 -> 2 lots; etc.
        lots = max(1, int(capital // capital_per_lot))
        total_qty = lots * LOT_SIZE

        # Find 09:25 AM candle
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

        ce_entry = calculate_option_price(spot_entry, atm_strike, base_tte, option_type="CE")["price"]
        pe_entry = calculate_option_price(spot_entry, atm_strike, base_tte, option_type="PE")["price"]
        ce_sl = round(ce_entry * (1.0 + leg_sl_pct), 2)
        pe_sl = round(pe_entry * (1.0 + leg_sl_pct), 2)

        ce_active = True
        pe_active = True
        ce_exit = None
        pe_exit = None
        ce_status = ""
        pe_status = ""

        cutoff = "14:15" if is_expiry else "15:15"

        for j in range(entry_idx + 1, len(day_candles)):
            c = day_candles[j]
            spot = c["close"]
            time_str = c["time_str"]

            bars_held = j - entry_idx
            tte = max(0.0001, base_tte - (bars_held / (75.0 * 365.0)))

            curr_ce = calculate_option_price(spot, atm_strike, tte, option_type="CE")["price"]
            curr_pe = calculate_option_price(spot, atm_strike, tte, option_type="PE")["price"]

            # CE SL
            if ce_active and curr_ce >= ce_sl:
                ce_active = False
                ce_exit = curr_ce
                ce_status = "SL Hit"
                # Quant Tweak: Move PE stop to breakeven
                if pe_active:
                    pe_sl = pe_entry

            # PE SL
            if pe_active and curr_pe >= pe_sl:
                pe_active = False
                pe_exit = curr_pe
                pe_status = "SL/BE Hit"
                # Quant Tweak: Move CE stop to breakeven
                if ce_active:
                    ce_sl = ce_entry

            if time_str >= cutoff:
                if ce_active:
                    ce_active = False
                    ce_exit = curr_ce
                    ce_status = "Decay Won"
                if pe_active:
                    pe_active = False
                    pe_exit = curr_pe
                    pe_status = "Decay Won"
                break

        if ce_active:
            ce_exit = curr_ce
            ce_status = "Decay Won"
        if pe_active:
            pe_exit = curr_pe
            pe_status = "Decay Won"

        # Trade Costs
        ce_cost = calculate_option_trade_costs(buy_price=ce_exit, sell_price=ce_entry, quantity=total_qty)
        pe_cost = calculate_option_trade_costs(buy_price=pe_exit, sell_price=pe_entry, quantity=total_qty)
        hedge_cost = 60.0 * lots

        gross = ce_cost["gross_pnl"] + pe_cost["gross_pnl"]
        charges = ce_cost["total_charges"] + pe_cost["total_charges"] + hedge_cost
        net = round(gross - charges, 2)

        start_of_day_cap = capital
        capital += net
        if capital > peak:
            peak = capital
        dd = peak - capital
        if dd > max_dd:
            max_dd = dd

        daily_results.append({
            "date": day_str,
            "lots": lots,
            "spot_entry": spot_entry,
            "atm_strike": atm_strike,
            "ce_entry": ce_entry,
            "pe_entry": pe_entry,
            "ce_exit": ce_exit,
            "pe_exit": pe_exit,
            "ce_status": ce_status,
            "pe_status": pe_status,
            "gross": gross,
            "charges": charges,
            "net": net,
            "capital_start": start_of_day_cap,
            "capital_end": capital
        })

    total_days = len(daily_results)
    wins = [d for d in daily_results if d["net"] > 0]
    losses = [d for d in daily_results if d["net"] <= 0]
    win_rate = (len(wins) / total_days * 100.0) if total_days > 0 else 0.0

    return {
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "net_profit": round(capital - initial_capital, 2),
        "return_pct": round((capital - initial_capital) / initial_capital * 100.0, 1),
        "total_days": total_days,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "max_drawdown": round(max_dd, 2),
        "daily": daily_results
    }

def main():
    print("=" * 105)
    print("  1-MONTH COMPOUNDED INTRADAY SIMULATION (STARTING CAPITAL: ₹50,000)")
    print("=" * 105)

    res = run_1month_compounded(initial_capital=50000.0, capital_per_lot=35000.0, leg_sl_pct=0.30)

    print(f"\nFINANCIAL PERFORMANCE SUMMARY (LAST 1 MONTH / 22 SESSIONS):")
    print(f"  • Starting Capital : ₹{res['initial_capital']:,.2f}")
    print(f"  • Ending Capital   : ₹{res['final_capital']:,.2f}")
    print(f"  • Net Pure Profit  : ₹{res['net_profit']:+,.2f}")
    print(f"  • 1-Month Return   : {res['return_pct']}%")
    print(f"  • Winning Days     : {res['wins']} / {res['total_days']} ({res['win_rate']}% Win Rate)")
    print(f"  • Maximum Drawdown : ₹{res['max_drawdown']:,.2f}\n")

    print("=" * 105)
    print(f"{'Date':<11} | {'Lots':<4} | {'ATM':<6} | {'CE Status':<12} | {'PE Status':<12} | {'Gross PnL':<11} | {'Taxes/Fees':<11} | {'Net PnL':<12} | {'Balance':<12}")
    print("-" * 105)

    for d in res["daily"]:
        gross_str = f"₹{d['gross']:+,.1f}"
        tax_str = f"₹{d['charges']:,.1f}"
        net_str = f"₹{d['net']:+,.1f}"
        bal_str = f"₹{d['capital_end']:,.1f}"
        print(f"{d['date']:<11} | {d['lots']:<4} | {d['atm_strike']:<6} | {d['ce_status']:<12} | {d['pe_status']:<12} | {gross_str:<11} | {tax_str:<11} | {net_str:<12} | {bal_str:<12}")

    print("=" * 105)

if __name__ == "__main__":
    main()
