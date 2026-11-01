"""
1-Year Real NSE 1-Minute Option-Candle Backtest via Upstox API v2
Evaluates ~250 trading days (Nov 2025 – Oct 2026) across 53 weekly expiries using
actual 1-minute OHLC candles of NSE NIFTY 50 weekly CE & PE contracts.
"""
import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from upstox_auth import api_get
from options_model import get_atm_strike
from friction import calculate_option_trade_costs
import test_upstox_real_backtest as real_bt
from test_upstox_real_backtest import (
    UPSTOX_CACHE_DIR,
    cached_get,
    get_all_expiries_and_contracts,
    get_contracts_for_expiry,
    simulate_real_day,
)

# Use actual NSE NIFTY contract lot size (65 qty)
real_bt.LOT_SIZE = 65

START_DATE = "2025-11-01"
END_DATE = "2026-10-30"


def fetch_1year_spot_1m() -> dict:
    start_dt = datetime.strptime(START_DATE, "%Y-%m-%d")
    end_dt = datetime.strptime(END_DATE, "%Y-%m-%d")

    chunks = []
    cur = start_dt
    while cur <= end_dt:
        nxt = min(cur + timedelta(days=24), end_dt)
        chunks.append((cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
        cur = nxt + timedelta(days=1)

    days = {}
    for f_str, t_str in chunks:
        rows = cached_get(
            f"spot_1m_{f_str}_{t_str}",
            lambda f=f_str, t=t_str: api_get(
                f"/historical-candle/NSE_INDEX%7CNifty%2050/1minute/{t}/{f}"
            )["data"]["candles"]
        )
        for row in rows:
            ts = row[0]
            day_str = ts[:10]
            time_str = ts[11:16]
            days.setdefault(day_str, {})[time_str] = {
                "time_str": time_str,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
            }

    return {d: [days[d][t] for t in sorted(days[d].keys())] for d in sorted(days.keys()) if START_DATE <= d <= END_DATE}


def prefetch_day_options(tasks: list):
    """Prefetch 1-minute option candles in parallel with gentle concurrency."""
    def worker(task):
        inst_key, day_str, is_expired = task
        safe_key = inst_key.replace("|", "_")
        cache_name = f"opt_1m_{safe_key}_{day_str}"
        path = os.path.join(UPSTOX_CACHE_DIR, f"{cache_name}.json")
        if os.path.exists(path):
            return True
        enc_key = urllib.parse.quote(inst_key, safe="")
        if is_expired:
            endpoint = f"/expired-instruments/historical-candle/{enc_key}/1minute/{day_str}/{day_str}"
        else:
            endpoint = f"/historical-candle/{enc_key}/1minute/{day_str}/{day_str}"
        for attempt in range(3):
            try:
                data = api_get(endpoint)["data"]["candles"]
                with open(path, "w") as f:
                    json.dump(data, f)
                return True
            except Exception as e:
                time.sleep(0.5 * (attempt + 1))
        return False

    to_fetch = []
    for inst_key, day_str, is_expired in tasks:
        safe_key = inst_key.replace("|", "_")
        path = os.path.join(UPSTOX_CACHE_DIR, f"opt_1m_{safe_key}_{day_str}.json")
        if not os.path.exists(path):
            to_fetch.append((inst_key, day_str, is_expired))

    if not to_fetch:
        return

    print(f"Downloading {len(to_fetch)} uncached 1-minute option candle series from Upstox...")
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(worker, t) for t in to_fetch]
        for _ in as_completed(futures):
            done += 1
            if done % 50 == 0 or done == len(to_fetch):
                print(f"  • Progress: {done}/{len(to_fetch)} option series cached")


def compute_metrics(results: list) -> dict:
    net_cum = 0.0
    peak = 0.0
    max_dd = 0.0
    wins = 0
    losses = 0
    gross_sum = 0.0
    charges_sum = 0.0

    for r in results:
        net_cum += r["net"]
        gross_sum += r["gross"]
        charges_sum += r["charges"]
        if r["net"] > 0:
            wins += 1
        else:
            losses += 1
        if net_cum > peak:
            peak = net_cum
        dd = peak - net_cum
        if dd > max_dd:
            max_dd = dd

    total = len(results)
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / total * 100.0) if total else 0.0,
        "gross": round(gross_sum, 2),
        "charges": round(charges_sum, 2),
        "net": round(net_cum, 2),
        "max_dd": round(max_dd, 2),
    }


def main():
    print("=" * 115)
    print(f"  1-YEAR REAL UPSTOX 1-MINUTE OPTION-CANDLE BACKTEST ({START_DATE} TO {END_DATE})")
    print("=" * 115)

    spot_by_day = fetch_1year_spot_1m()
    trading_days = sorted(spot_by_day.keys())
    print(f"Loaded 1-minute NIFTY 50 Spot candles for {len(trading_days)} trading sessions.")

    expired_expiries, active_expiries, active_contracts = get_all_expiries_and_contracts()
    all_expiries = sorted(expired_expiries + active_expiries)

    # Map each trading day to its nearest weekly expiry and ATM CE/PE contracts
    day_plan = []
    option_tasks = []
    needed_expiries = sorted(list({
        next((e for e in all_expiries if e >= d), None)
        for d in trading_days
    } - {None}))

    print(f"Loading option contract chains for {len(needed_expiries)} weekly expiries...")
    expiry_contracts_map = {}
    for exp in needed_expiries:
        contracts, is_exp = get_contracts_for_expiry(exp, expired_expiries, active_contracts)
        expiry_contracts_map[exp] = (contracts, is_exp)

    for day_str in trading_days:
        spot_bars = spot_by_day[day_str]
        entry_bar = next((b for b in spot_bars if b["time_str"] >= "09:25"), None)
        if not entry_bar:
            continue
        atm_strike = get_atm_strike(entry_bar["close"], step=50)
        expiry = next((e for e in all_expiries if e >= day_str), None)
        if not expiry:
            continue
        contracts, is_expired = expiry_contracts_map[expiry]
        ce_c = next((c for c in contracts if int(round(c["strike_price"])) == atm_strike and c["instrument_type"] == "CE"), None)
        pe_c = next((c for c in contracts if int(round(c["strike_price"])) == atm_strike and c["instrument_type"] == "PE"), None)
        if ce_c and pe_c:
            day_plan.append((day_str, expiry, contracts, is_expired))
            option_tasks.append((ce_c["instrument_key"], day_str, is_expired))
            option_tasks.append((pe_c["instrument_key"], day_str, is_expired))

    prefetch_day_options(option_tasks)

    # Run 3 execution models across all ~248 sessions
    res_close_0 = []      # 1m Close SL check, ₹0 slippage
    res_high_05 = []      # 1m High SL check, ₹0.50 slippage (Realistic SL-M/Limit)
    res_high_15 = []      # 1m High SL check, ₹1.50 slippage (Harsh fast-spike slippage)

    for day_str, expiry, contracts, is_expired in day_plan:
        spot_bars = spot_by_day[day_str]
        r1 = simulate_real_day(day_str, spot_bars, expiry, contracts, is_expired,
                               leg_sl_pct=0.30, lots=1, use_high_for_sl=False, slippage_pts=0.0)
        r2 = simulate_real_day(day_str, spot_bars, expiry, contracts, is_expired,
                               leg_sl_pct=0.30, lots=1, use_high_for_sl=True, slippage_pts=0.5)
        r3 = simulate_real_day(day_str, spot_bars, expiry, contracts, is_expired,
                               leg_sl_pct=0.30, lots=1, use_high_for_sl=True, slippage_pts=1.5)
        if r1 and r2 and r3:
            res_close_0.append(r1)
            res_high_05.append(r2)
            res_high_15.append(r3)

    m_close = compute_metrics(res_close_0)
    m_real = compute_metrics(res_high_05)
    m_harsh = compute_metrics(res_high_15)

    # 1. Execution Model Comparison
    print("\n" + "=" * 115)
    print("  1. EXECUTION MODEL COMPARISON (1 FULL YEAR — 1 LOT = 65 QTY ACTUAL NSE CONTRACT SIZE)")
    print("=" * 115)
    print(f"{'Execution Model':<46} | {'Sessions':<8} | {'Win Rate':<14} | {'Gross PnL':<14} | {'Taxes/Fees':<12} | {'Net In-Pocket':<14} | {'Max Drawdown'}")
    print("-" * 115)
    for label, m in [
        ("A. 1m Candle Close SL Check (₹0.00 Slippage)", m_close),
        ("B. 1m Candle High SL Trigger (+₹0.50 Slippage)", m_real),
        ("C. 1m Candle High SL Trigger (+₹1.50 Slippage)", m_harsh),
    ]:
        wr_str = f"{m['wins']}/{m['total']} ({m['win_rate']:.1f}%)"
        print(f"{label:<46} | {m['total']:<8} | {wr_str:<14} | ₹{m['gross']:+12,.0f} | ₹{m['charges']:10,.0f} | ₹{m['net']:+12,.0f} | ₹{m['max_dd']:,.0f}")

    # 2. Month-by-Month Breakdown (using Realistic Model B: 1m High + ₹0.50 slippage)
    print("\n" + "=" * 115)
    print("  2. MONTH-BY-MONTH PERFORMANCE BREAKDOWN (MODEL B: REAL 1M HIGH SL + ₹0.50 SLIPPAGE, 1 LOT = 65 QTY)")
    print("=" * 115)
    print(f"{'Month':<10} | {'Sessions':<8} | {'Wins':<6} | {'Losses':<6} | {'Win Rate':<10} | {'Gross PnL':<14} | {'Taxes/Fees':<12} | {'Net In-Pocket':<14} | {'Max DD':<10} | {'Double SLs'}")
    print("-" * 115)

    by_month = {}
    for r in res_high_05:
        ym = r["date"][:7]
        by_month.setdefault(ym, []).append(r)

    for ym in sorted(by_month.keys()):
        m_rows = by_month[ym]
        mm = compute_metrics(m_rows)
        dbl_sl = sum(1 for r in m_rows if "Decay Won" not in (r["ce_status"], r["pe_status"]))
        print(f"{ym:<10} | {mm['total']:<8} | {mm['wins']:<6} | {mm['losses']:<6} | {mm['win_rate']:>6.1f}%   | ₹{mm['gross']:+12,.0f} | ₹{mm['charges']:10,.0f} | ₹{mm['net']:+12,.0f} | ₹{mm['max_dd']:8,.0f} | {dbl_sl}/{mm['total']}")

    # 3. Day-of-Week & Expiry vs Non-Expiry Breakdown
    print("\n" + "=" * 115)
    print("  3. DAY-OF-WEEK & EXPIRY REGIME ANALYSIS (MODEL B: REAL 1M HIGH SL + ₹0.50 SLIPPAGE, 1 LOT = 65 QTY)")
    print("=" * 115)
    print(f"{'Day / Regime':<24} | {'Sessions':<8} | {'Win Rate':<15} | {'Gross PnL':<14} | {'Taxes/Fees':<12} | {'Net In-Pocket':<14} | {'Double SL Rate'}")
    print("-" * 115)

    dow_names = ["Monday (1 DTE)", "Tuesday (0 DTE Expiry)", "Wednesday (6 DTE)", "Thursday (5 DTE)", "Friday (4 DTE)"]
    by_dow = {i: [] for i in range(5)}
    expiry_days = []
    non_expiry_days = []

    for r in res_high_05:
        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        if dt.weekday() in by_dow:
            by_dow[dt.weekday()].append(r)
        if r["is_expiry"]:
            expiry_days.append(r)
        else:
            non_expiry_days.append(r)

    for wd in range(5):
        rows = by_dow[wd]
        if not rows:
            continue
        mm = compute_metrics(rows)
        dbl = sum(1 for r in rows if "Decay Won" not in (r["ce_status"], r["pe_status"]))
        print(f"{dow_names[wd]:<24} | {mm['total']:<8} | {mm['wins']:>2}/{mm['total']:<2} ({mm['win_rate']:>5.1f}%)  | ₹{mm['gross']:+12,.0f} | ₹{mm['charges']:10,.0f} | ₹{mm['net']:+12,.0f} | {dbl}/{mm['total']} ({dbl/mm['total']*100:.1f}%)")

    print("-" * 115)
    for label, rows in [("ALL EXPIRY DAYS (0 DTE)", expiry_days), ("NON-EXPIRY DAYS (1-6 DTE)", non_expiry_days)]:
        mm = compute_metrics(rows)
        dbl = sum(1 for r in rows if "Decay Won" not in (r["ce_status"], r["pe_status"]))
        print(f"{label:<24} | {mm['total']:<8} | {mm['wins']:>3}/{mm['total']:<3} ({mm['win_rate']:>4.1f}%)  | ₹{mm['gross']:+12,.0f} | ₹{mm['charges']:10,.0f} | ₹{mm['net']:+12,.0f} | {dbl}/{mm['total']} ({dbl/mm['total']*100:.1f}%)")
    print("=" * 115)


if __name__ == "__main__":
    main()
