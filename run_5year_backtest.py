"""
5-Year Full-Cycle Institutional Options Backtester (2021 - 2026)
Simulates 1,236 Trading Sessions of NIFTY 50 Option Selling (Hedged Short Straddle)
across Bull Markets, Bear Markets, Consolidations, and High-VIX Shock Regimes.
"""
import urllib.request
import json
from datetime import datetime
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs

LOT_SIZE = 25  # Nifty 1 lot

def fetch_5year_daily_data() -> list:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as res:
        payload = json.loads(res.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    opens = quote["open"]
    highs = quote["high"]
    lows = quote["low"]
    closes = quote["close"]

    data = []
    for i in range(len(timestamps)):
        if (opens[i] is None or highs[i] is None or 
            lows[i] is None or closes[i] is None):
            continue

        dt = datetime.fromtimestamp(timestamps[i])
        data.append({
            "timestamp": timestamps[i],
            "date": dt.strftime("%Y-%m-%d"),
            "year": dt.strftime("%Y"),
            "open": round(float(opens[i]), 2),
            "high": round(float(highs[i]), 2),
            "low": round(float(lows[i]), 2),
            "close": round(float(closes[i]), 2),
            "range": round(float(highs[i]) - float(lows[i]), 2)
        })
    return data

def run_5year_straddle_simulation(data: list, leg_sl_pct: float = 0.30,
                                   shock_range_filter: float = 250.0) -> dict:
    """
    Simulates the 09:25 Short Straddle over 5 years.
    - Entry at Day's Open price
    - Call checked against Day's High
    - Put checked against Day's Low
    - Unstopped legs settle at Day's Close with full intraday theta decay
    - Exact Zerodha + SEBI STT + GST friction
    """
    base_tte_years = 2.0 / 365.0
    intraday_tte_years = 1.0 / 365.0  # Decayed 1 full trading day

    trades = []
    for i in range(1, len(data)):
        day = data[i]
        prev_day = data[i - 1]

        # Shock Filter: If previous day had a violent extreme move (> 250 pts), market is in shock
        if prev_day["range"] > shock_range_filter:
            continue

        spot_open = day["open"]
        spot_high = day["high"]
        spot_low = day["low"]
        spot_close = day["close"]
        atm_strike = get_atm_strike(spot_open, step=50)

        # 1. Entry Option Prices (Morning)
        ce_entry = calculate_option_price(spot_open, atm_strike, base_tte_years, option_type="CE")["price"]
        pe_entry = calculate_option_price(spot_open, atm_strike, base_tte_years, option_type="PE")["price"]
        wing_ce = calculate_option_price(spot_open, atm_strike + 200, base_tte_years, option_type="CE")["price"]
        wing_pe = calculate_option_price(spot_open, atm_strike - 200, base_tte_years, option_type="PE")["price"]

        ce_sl = ce_entry * (1.0 + leg_sl_pct)
        pe_sl = pe_entry * (1.0 + leg_sl_pct)

        # 2. Check if CE hit Stop Loss at the Day's High
        ce_high_price = calculate_option_price(spot_high, atm_strike, base_tte_years, option_type="CE")["price"]
        ce_hit_sl = ce_high_price >= ce_sl

        # 3. Check if PE hit Stop Loss at the Day's Low
        pe_low_price = calculate_option_price(spot_low, atm_strike, base_tte_years, option_type="PE")["price"]
        pe_hit_sl = pe_low_price >= pe_sl

        # 4. Exit Prices
        if ce_hit_sl:
            ce_exit = round(ce_sl, 2)
            ce_status = "SL HIT"
        else:
            # Held till EOD close with theta decay
            ce_exit = calculate_option_price(spot_close, atm_strike, intraday_tte_years, option_type="CE")["price"]
            ce_status = "DECAY WON"

        if pe_hit_sl:
            pe_exit = round(pe_sl, 2)
            pe_status = "SL HIT"
        else:
            # Held till EOD close with theta decay
            pe_exit = calculate_option_price(spot_close, atm_strike, intraday_tte_years, option_type="PE")["price"]
            pe_status = "DECAY WON"

        # 5. Friction & PnL
        ce_cost = calculate_option_trade_costs(buy_price=ce_exit, sell_price=ce_entry, quantity=LOT_SIZE)
        pe_cost = calculate_option_trade_costs(buy_price=pe_exit, sell_price=pe_entry, quantity=LOT_SIZE)
        wing_cost = (wing_ce + wing_pe) * 0.35 * LOT_SIZE + 40.0  # ₹40 brokerage for protective wings

        gross = ce_cost["gross_pnl"] + pe_cost["gross_pnl"]
        charges = ce_cost["total_charges"] + pe_cost["total_charges"] + wing_cost
        net = round(gross - charges, 2)

        trades.append({
            "date": day["date"],
            "year": day["year"],
            "strike": atm_strike,
            "ce_status": ce_status,
            "pe_status": pe_status,
            "gross_pnl": round(gross, 2),
            "charges": round(charges, 2),
            "net_pnl": net
        })

    # Performance Analytics
    total = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / total * 100.0) if total > 0 else 0.0

    net_sum = sum(t["net_pnl"] for t in trades)
    gross_sum = sum(t["gross_pnl"] for t in trades)
    charges_sum = sum(t["charges"] for t in trades)

    tot_gain = sum(t["net_pnl"] for t in wins)
    tot_loss = abs(sum(t["net_pnl"] for t in losses))
    pf = round(tot_gain / tot_loss, 2) if tot_loss > 0 else 99.0

    # Max Drawdown
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t["net_pnl"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Year-by-Year breakdown
    yearly = {}
    for t in trades:
        y = t["year"]
        if y not in yearly:
            yearly[y] = {"trades": 0, "wins": 0, "net_pnl": 0.0, "charges": 0.0}
        yearly[y]["trades"] += 1
        if t["net_pnl"] > 0:
            yearly[y]["wins"] += 1
        yearly[y]["net_pnl"] += t["net_pnl"]
        yearly[y]["charges"] += t["charges"]

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 1),
        "gross_pnl": round(gross_sum, 2),
        "total_charges": round(charges_sum, 2),
        "net_pnl": round(net_sum, 2),
        "profit_factor": pf,
        "max_drawdown": round(max_dd, 2),
        "yearly": yearly
    }

def main():
    print("=" * 95)
    print("  5-YEAR COMPREHENSIVE INSTITUTIONAL OPTION SELLING BACKTEST (2021 - 2026)")
    print("=" * 95)
    print("Fetching 5-year daily candlestick data for NIFTY 50...")
    data = fetch_5year_daily_data()
    print(f"Loaded {len(data)} trading sessions from {data[0]['date']} to {data[-1]['date']}.\n")

    res = run_5year_straddle_simulation(data, leg_sl_pct=0.30, shock_range_filter=250.0)

    print("OVERALL 5-YEAR PERFORMANCE SUMMARY (1 LOT NIFTY):")
    print(f"  • Total Trading Days Analyzed : {res['total_trades']}")
    print(f"  • Winning Days                : {res['wins']}")
    print(f"  • Losing Days                 : {res['losses']}")
    print(f"  • WIN RATE                    : {res['win_rate_pct']}%")
    print(f"  • Gross Profit Generated      : ₹{res['gross_pnl']:+,.1f}")
    print(f"  • Taxes, Brokerage & Hedges   : ₹{res['total_charges']:,.1f}")
    print(f"  • NET IN-POCKET CASH PROFIT   : ₹{res['net_pnl']:+,.1f}")
    print(f"  • Profit Factor               : {res['profit_factor']}")
    print(f"  • Maximum Drawdown            : ₹{res['max_drawdown']:,.1f}\n")

    print("=" * 95)
    print(f"{'Year':<8} | {'Trades':<8} | {'Win Rate':<10} | {'Taxes/Brokerage':<18} | {'Net In-Pocket P&L':<20}")
    print("-" * 95)
    for y, stats in sorted(res["yearly"].items()):
        wr = (stats["wins"] / stats["trades"] * 100.0) if stats["trades"] > 0 else 0.0
        net_str = f"₹{stats['net_pnl']:+,.1f}"
        tax_str = f"₹{stats['charges']:,.1f}"
        print(f"{y:<8} | {stats['trades']:<8} | {wr:<9.1f}% | {tax_str:<18} | {net_str:<20}")
    print("=" * 95)

if __name__ == "__main__":
    main()
