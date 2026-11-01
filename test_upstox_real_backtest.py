"""
Real 1-Minute NSE Option-Candle Backtest via Upstox API v2
Compares the 09:25 ATM Short Straddle (30% SL + Breakeven Trail) on:
  1. Synthetic Black-Scholes (5m Spot Close, fixed 15% IV, constant 2 DTE)
  2. Real Upstox 1-Minute Option Candles (actual NSE CE/PE contracts, 1m High SL trigger)
"""
import json
import os
import urllib.parse
from datetime import datetime
from upstox_auth import api_get
from options_model import get_atm_strike
from friction import calculate_option_trade_costs
from test_1month_compounded import run_1month_compounded, LOT_SIZE

UPSTOX_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache", "upstox")
os.makedirs(UPSTOX_CACHE_DIR, exist_ok=True)


def cached_get(cache_name: str, loader):
    path = os.path.join(UPSTOX_CACHE_DIR, f"{cache_name}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    data = loader()
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def fetch_spot_1m_by_day() -> dict:
    # Fetch two chunks to cover 2026-09-25 to 2026-10-30 within Upstox's 30-day 1m limit
    c1 = cached_get(
        "spot_1m_2026-09-25_2026-10-10",
        lambda: api_get("/historical-candle/NSE_INDEX%7CNifty%2050/1minute/2026-10-10/2026-09-25")["data"]["candles"]
    )
    c2 = cached_get(
        "spot_1m_2026-10-11_2026-10-30",
        lambda: api_get("/historical-candle/NSE_INDEX%7CNifty%2050/1minute/2026-10-30/2026-10-11")["data"]["candles"]
    )
    days = {}
    for row in (c1 + c2):
        # row: ['2026-10-27T09:15:00+05:30', open, high, low, close, vol, oi]
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
    return {d: [days[d][t] for t in sorted(days[d].keys())] for d in sorted(days.keys())}


def get_all_expiries_and_contracts():
    expired_expiries = cached_get(
        "expired_expiries",
        lambda: api_get("/expired-instruments/expiries", {"instrument_key": "NSE_INDEX|Nifty 50"})["data"]
    )
    active_contracts = cached_get(
        "active_contracts",
        lambda: api_get("/option/contract", {"instrument_key": "NSE_INDEX|Nifty 50"})["data"]
    )
    active_expiries = sorted(list({c["expiry"] for c in active_contracts}))
    return sorted(expired_expiries), active_expiries, active_contracts


def get_contracts_for_expiry(expiry: str, expired_expiries: list, active_contracts: list) -> tuple[list, bool]:
    if expiry in expired_expiries:
        contracts = cached_get(
            f"expired_contracts_{expiry}",
            lambda: api_get("/expired-instruments/option/contract", {
                "instrument_key": "NSE_INDEX|Nifty 50",
                "expiry_date": expiry
            })["data"]
        )
        return contracts, True
    else:
        return [c for c in active_contracts if c["expiry"] == expiry], False


def fetch_option_day_candles(instrument_key: str, trade_date: str, is_expired: bool) -> dict:
    safe_key = instrument_key.replace("|", "_")
    cache_name = f"opt_1m_{safe_key}_{trade_date}"
    enc_key = urllib.parse.quote(instrument_key, safe="")
    if is_expired:
        endpoint = f"/expired-instruments/historical-candle/{enc_key}/1minute/{trade_date}/{trade_date}"
    else:
        endpoint = f"/historical-candle/{enc_key}/1minute/{trade_date}/{trade_date}"

    raw = cached_get(cache_name, lambda: api_get(endpoint)["data"]["candles"])
    by_time = {}
    for row in raw:
        time_str = row[0][11:16]
        by_time[time_str] = {
            "time_str": time_str,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]),
        }
    return by_time


def simulate_real_day(day_str: str, spot_bars: list, expiry: str, contracts: list,
                      is_expired: bool, leg_sl_pct: float = 0.30, lots: int = 1,
                      use_high_for_sl: bool = True, slippage_pts: float = 0.0) -> dict:
    # Find 09:25 spot bar
    entry_bar = next((b for b in spot_bars if b["time_str"] >= "09:25"), None)
    if not entry_bar:
        return None

    spot_entry = entry_bar["close"]
    atm_strike = get_atm_strike(spot_entry, step=50)

    ce_contract = next((c for c in contracts if int(round(c["strike_price"])) == atm_strike and c["instrument_type"] == "CE"), None)
    pe_contract = next((c for c in contracts if int(round(c["strike_price"])) == atm_strike and c["instrument_type"] == "PE"), None)
    if not ce_contract or not pe_contract:
        return None

    ce_bars = fetch_option_day_candles(ce_contract["instrument_key"], day_str, is_expired)
    pe_bars = fetch_option_day_candles(pe_contract["instrument_key"], day_str, is_expired)

    all_times = sorted(set(ce_bars.keys()) & set(pe_bars.keys()))
    trade_times = [t for t in all_times if t >= "09:25"]
    if len(trade_times) < 5:
        return None

    t0 = trade_times[0]
    ce_entry = ce_bars[t0]["close"]
    pe_entry = pe_bars[t0]["close"]
    ce_sl = round(ce_entry * (1.0 + leg_sl_pct), 2)
    pe_sl = round(pe_entry * (1.0 + leg_sl_pct), 2)

    ce_active = True
    pe_active = True
    ce_exit = ce_entry
    pe_exit = pe_entry
    ce_status = ""
    pe_status = ""

    is_expiry_day = (day_str == expiry)
    cutoff = "14:15" if is_expiry_day else "15:15"

    for t in trade_times[1:]:
        ce_b = ce_bars[t]
        pe_b = pe_bars[t]

        ce_check_price = ce_b["high"] if use_high_for_sl else ce_b["close"]
        pe_check_price = pe_b["high"] if use_high_for_sl else pe_b["close"]

        # 1. Check CE SL
        if ce_active and ce_check_price >= ce_sl:
            ce_active = False
            # Fill at SL price (or gap open if bar opened above SL) + slippage
            raw_fill = max(ce_sl, ce_b["open"]) if use_high_for_sl else ce_b["close"]
            ce_exit = round(raw_fill + slippage_pts, 2)
            ce_status = "BE Hit" if ce_sl == ce_entry else "SL Hit"
            if pe_active and pe_b["close"] < pe_entry:
                pe_sl = pe_entry

        # 2. Check PE SL
        if pe_active and pe_check_price >= pe_sl:
            pe_active = False
            raw_fill = max(pe_sl, pe_b["open"]) if use_high_for_sl else pe_b["close"]
            pe_exit = round(raw_fill + slippage_pts, 2)
            pe_status = "BE Hit" if pe_sl == pe_entry else "SL Hit"
            if ce_active and ce_b["close"] < ce_entry:
                ce_sl = ce_entry

        if (not ce_active and not pe_active) or t >= cutoff:
            if ce_active:
                ce_active = False
                ce_exit = ce_b["close"]
                ce_status = "Decay Won"
            if pe_active:
                pe_active = False
                pe_exit = pe_b["close"]
                pe_status = "Decay Won"
            break

    total_qty = lots * LOT_SIZE
    ce_cost = calculate_option_trade_costs(buy_price=ce_exit, sell_price=ce_entry, quantity=total_qty)
    pe_cost = calculate_option_trade_costs(buy_price=pe_exit, sell_price=pe_entry, quantity=total_qty)
    hedge_cost = 60.0 * lots

    gross = round(ce_cost["gross_pnl"] + pe_cost["gross_pnl"], 2)
    charges = round(ce_cost["total_charges"] + pe_cost["total_charges"] + hedge_cost, 2)
    net = round(gross - charges, 2)

    return {
        "date": day_str,
        "expiry": expiry,
        "is_expiry": is_expiry_day,
        "spot_entry": spot_entry,
        "atm_strike": atm_strike,
        "ce_symbol": ce_contract["trading_symbol"],
        "pe_symbol": pe_contract["trading_symbol"],
        "ce_entry": ce_entry,
        "pe_entry": pe_entry,
        "ce_exit": ce_exit,
        "pe_exit": pe_exit,
        "ce_status": ce_status,
        "pe_status": pe_status,
        "gross": gross,
        "charges": charges,
        "net": net,
    }


def main():
    print("Fetching synthetic 1-month backtest baseline...")
    synth = run_1month_compounded(initial_capital=50000.0, capital_per_lot=35000.0, leg_sl_pct=0.30)
    synth_by_date = {d["date"]: d for d in synth["daily"]}
    target_days = [d["date"] for d in synth["daily"]]

    print("Fetching real 1-minute NIFTY spot & option candles from Upstox...")
    spot_by_day = fetch_spot_1m_by_day()
    expired_expiries, active_expiries, active_contracts = get_all_expiries_and_contracts()
    all_expiries = sorted(expired_expiries + active_expiries)

    real_high_results = []
    real_close_results = []

    for day_str in target_days:
        if day_str not in spot_by_day:
            continue
        expiry = next((e for e in all_expiries if e >= day_str), None)
        if not expiry:
            continue
        contracts, is_expired = get_contracts_for_expiry(expiry, expired_expiries, active_contracts)

        res_high = simulate_real_day(day_str, spot_by_day[day_str], expiry, contracts, is_expired,
                                     leg_sl_pct=0.30, lots=1, use_high_for_sl=True, slippage_pts=0.5)
        res_close = simulate_real_day(day_str, spot_by_day[day_str], expiry, contracts, is_expired,
                                      leg_sl_pct=0.30, lots=1, use_high_for_sl=False, slippage_pts=0.0)
        if res_high:
            real_high_results.append(res_high)
        if res_close:
            real_close_results.append(res_close)

    print("\n" + "=" * 128)
    print("  REAL UPSTOX 1-MINUTE OPTION CANDLES vs. SYNTHETIC BLACK-SCHOLES (LAST 22 TRADING SESSIONS, 1 LOT = 25 QTY)")
    print("=" * 128)
    header = (f"{'Date':<10} | {'Expiry':<10} | {'ATM':<5} | "
              f"{'Real CE (In->Out)':<19} | {'Real PE (In->Out)':<19} | "
              f"{'Real Leg Status':<19} | {'Real Net PnL':<13} | {'Synth Net PnL':<13} | {'Diff':<10}")
    print(header)
    print("-" * 128)

    real_cum = 0.0
    synth_cum = 0.0
    for r in real_high_results:
        d = r["date"]
        s = synth_by_date.get(d, {})
        s_net = s.get("net", 0.0)
        diff = r["net"] - s_net
        real_cum += r["net"]
        synth_cum += s_net

        exp_tag = f"{r['expiry']}*" if r["is_expiry"] else r["expiry"]
        ce_str = f"{r['ce_entry']:>6.1f}->{r['ce_exit']:<6.1f}"
        pe_str = f"{r['pe_entry']:>6.1f}->{r['pe_exit']:<6.1f}"
        status_str = f"{r['ce_status']}/{r['pe_status']}"
        print(f"{d:<10} | {exp_tag:<10} | {r['atm_strike']:<5} | "
              f"{ce_str:<19} | {pe_str:<19} | "
              f"{status_str:<19} | ₹{r['net']:+10,.2f}  | ₹{s_net:+10,.2f}  | ₹{diff:+8,.2f}")

    print("=" * 128)
    real_wins = sum(1 for r in real_high_results if r["net"] > 0)
    close_wins = sum(1 for r in real_close_results if r["net"] > 0)
    close_net = sum(r["net"] for r in real_close_results)
    total_n = len(real_high_results)

    print("\nHEAD-TO-HEAD SUMMARY (22 SESSIONS, 1 LOT = 25 QTY):")
    print(f"  1. Synthetic Black-Scholes (5m Spot Close, Fixed 15% IV, 2 DTE):")
    print(f"     • Win Rate : {synth['wins']}/{synth['total_days']} ({synth['win_rate']}%)")
    print(f"     • Net PnL  : ₹{synth_cum:+,.2f}")
    print(f"  2. Real Upstox 1m Option Candles (1m Close SL check, 0 slippage):")
    print(f"     • Win Rate : {close_wins}/{total_n} ({close_wins/total_n*100:.1f}%)")
    print(f"     • Net PnL  : ₹{close_net:+,.2f}")
    print(f"  3. Real Upstox 1m Option Candles (Realistic: 1m High SL trigger + ₹0.50 slippage):")
    print(f"     • Win Rate : {real_wins}/{total_n} ({real_wins/total_n*100:.1f}%)")
    print(f"     • Net PnL  : ₹{real_cum:+,.2f}  (Scaled to actual NSE 65 qty/lot: ₹{real_cum * (65/25):+,.2f})")
    print("=" * 128)


if __name__ == "__main__":
    main()
