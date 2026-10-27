"""
5-Year Intraday Institutional Straddle Engine (2021 - 2026)
Simulates 1,235 trading sessions of 09:25 AM Intraday NIFTY Short Straddle
with realistic penny-hedge margin relief, 30% individual leg stops, and real Zerodha taxes.
"""
import urllib.request
import json
from datetime import datetime
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs

LOT_SIZE = 25

def fetch_data():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=5y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as res:
        payload = json.loads(res.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    q = result["indicators"]["quote"][0]

    data = []
    for i in range(len(timestamps)):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if o is None or h is None or l is None or c is None:
            continue
        dt = datetime.fromtimestamp(timestamps[i])
        data.append({
            "date": dt.strftime("%Y-%m-%d"),
            "year": dt.strftime("%Y"),
            "open": round(float(o), 2),
            "high": round(float(h), 2),
            "low": round(float(l), 2),
            "close": round(float(c), 2)
        })
    return data

def run_5year_intraday_straddle(data: list, leg_sl_pct: float = 0.30, penny_hedge_cost: float = 75.0):
    base_tte_years = 2.0 / 365.0
    intraday_tte_years = 1.0 / 365.0

    trades = []
    for day in data:
        spot_open = day["open"]
        spot_high = day["high"]
        spot_low = day["low"]
        spot_close = day["close"]
        atm_strike = get_atm_strike(spot_open, step=50)

        # 1. Entry Option Prices (Morning 09:25)
        ce_entry = calculate_option_price(spot_open, atm_strike, base_tte_years, option_type="CE")["price"]
        pe_entry = calculate_option_price(spot_open, atm_strike, base_tte_years, option_type="PE")["price"]

        ce_sl = round(ce_entry * (1.0 + leg_sl_pct), 2)
        pe_sl = round(pe_entry * (1.0 + leg_sl_pct), 2)

        # Delta approximation: ATM delta is ~0.50
        # Price move required to hit +30% SL: ~ (0.30 * entry_prem) / 0.50 = 0.60 * entry_prem
        upside_sl_pts = (ce_entry * leg_sl_pct) / 0.50
        downside_sl_pts = (pe_entry * leg_sl_pct) / 0.50

        high_move = spot_high - spot_open
        low_move = spot_open - spot_low

        ce_hit = high_move >= upside_sl_pts
        pe_hit = low_move >= downside_sl_pts

        # Determine outcome based on intraday market path
        if ce_hit and pe_hit:
            # Whipsaw day: both stops hit
            ce_exit = ce_sl
            pe_exit = pe_sl
            outcome = "Double SL (Whipsaw)"
        elif ce_hit and not pe_hit:
            # Uptrend day: CE stopped out, PE decayed into close
            ce_exit = ce_sl
            pe_exit = calculate_option_price(spot_close, atm_strike, intraday_tte_years, option_type="PE")["price"]
            outcome = "CE SL, PE Decayed"
        elif pe_hit and not ce_hit:
            # Downtrend day: PE stopped out, CE decayed into close
            pe_exit = pe_sl
            ce_exit = calculate_option_price(spot_close, atm_strike, intraday_tte_years, option_type="CE")["price"]
            outcome = "PE SL, CE Decayed"
        else:
            # Rangebound day (80% of days): BOTH decayed into close
            ce_exit = calculate_option_price(spot_close, atm_strike, intraday_tte_years, option_type="CE")["price"]
            pe_exit = calculate_option_price(spot_close, atm_strike, intraday_tte_years, option_type="PE")["price"]
            outcome = "Both Decayed (Max Theta)"

        # 2. Transaction Costs & Net PnL
        ce_cost = calculate_option_trade_costs(buy_price=ce_exit, sell_price=ce_entry, quantity=LOT_SIZE)
        pe_cost = calculate_option_trade_costs(buy_price=pe_exit, sell_price=pe_entry, quantity=LOT_SIZE)

        gross = ce_cost["gross_pnl"] + pe_cost["gross_pnl"]
        # Brokerage on straddle (₹40 CE + ₹40 PE) + penny hedge cost (₹75) + STT/taxes
        charges = ce_cost["total_charges"] + pe_cost["total_charges"] + penny_hedge_cost
        net = round(gross - charges, 2)

        trades.append({
            "date": day["date"],
            "year": day["year"],
            "net_pnl": net,
            "gross_pnl": round(gross, 2),
            "charges": round(charges, 2),
            "outcome": outcome
        })

    # Summary
    total = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / total * 100.0) if total > 0 else 0.0

    gross_total = sum(t["gross_pnl"] for t in trades)
    charges_total = sum(t["charges"] for t in trades)
    net_total = sum(t["net_pnl"] for t in trades)

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

    yearly = {}
    for t in trades:
        y = t["year"]
        if y not in yearly:
            yearly[y] = {"trades": 0, "wins": 0, "net": 0.0, "charges": 0.0}
        yearly[y]["trades"] += 1
        if t["net_pnl"] > 0:
            yearly[y]["wins"] += 1
        yearly[y]["net"] += t["net_pnl"]
        yearly[y]["charges"] += t["charges"]

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "gross": round(gross_total, 2),
        "charges": round(charges_total, 2),
        "net": round(net_total, 2),
        "profit_factor": pf,
        "max_drawdown": round(max_dd, 2),
        "yearly": yearly
    }

def main():
    data = fetch_data()
    print("=" * 95)
    print("  5-YEAR INTRADAY INSTITUTIONAL SHORT STRADDLE SIMULATION (2021 - 2026)")
    print(f"  Total Historical Trading Sessions: {len(data)} Days")
    print("=" * 95)

    for sl in [0.25, 0.30, 0.35]:
        res = run_5year_intraday_straddle(data, leg_sl_pct=sl, penny_hedge_cost=60.0)
        print(f"\nCONFIGURATION: Leg Stop-Loss = {sl*100:.0f}%")
        print(f"  • Total Trading Days   : {res['total']}")
        print(f"  • Winning Days         : {res['wins']} | Losing Days: {res['losses']}")
        print(f"  • 5-YEAR WIN RATE      : {res['win_rate']}%")
        print(f"  • Gross Profit         : ₹{res['gross']:+,.1f}")
        print(f"  • Total Charges & Fees : ₹{res['charges']:,.1f}")
        print(f"  • NET IN-POCKET PROFIT : ₹{res['net']:+,.1f}")
        print(f"  • Profit Factor        : {res['profit_factor']}")
        print(f"  • Maximum Drawdown     : ₹{res['max_drawdown']:,.1f}")
        print("-" * 95)
        print(f"  Year-by-Year Net Cash Breakdown:")
        for y, s in sorted(res["yearly"].items()):
            wr = (s['wins'] / s['trades'] * 100.0) if s['trades'] > 0 else 0.0
            print(f"    {y}: {s['trades']} days | Win Rate: {wr:4.1f}% | Net Cash: ₹{s['net']:+,.1f}")

if __name__ == "__main__":
    main()
