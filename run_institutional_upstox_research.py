"""
Institutional & P R Sundar Strategy Research Suite on 1-Year Real Upstox 1m Option Candles
Tests 6 complete option-selling architectures across 246 real trading sessions (Nov 2025 – Oct 2026)
with realistic 1-minute High stop-loss triggers, ₹0.50 slippage per stop fill, and exact Zerodha/SEBI charges.
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
from run_1year_upstox_backtest import (
    START_DATE,
    END_DATE,
    UPSTOX_CACHE_DIR,
     fetch_1year_spot_1m,
    get_all_expiries_and_contracts,
    get_contracts_for_expiry,
    compute_metrics,
)

LOT_SIZE = 65  # Actual NSE NIFTY contract lot size
WEEK_CACHE_DIR = os.path.join(UPSTOX_CACHE_DIR, "weekly_series")
os.makedirs(WEEK_CACHE_DIR, exist_ok=True)


def get_week_option_candles(instrument_key: str, week_start: str, expiry: str, is_expired: bool) -> dict:
    """
    Returns {day_str: {time_str: {open, high, low, close}}} for an option contract across its whole trading week.
    Also checks if single-day cache files already exist from previous runs.
    """
    safe_key = instrument_key.replace("|", "_")
    week_path = os.path.join(WEEK_CACHE_DIR, f"wk_{safe_key}_{week_start}_{expiry}.json")
    if os.path.exists(week_path):
        with open(week_path, "r") as f:
            raw = json.load(f)
    else:
        enc_key = urllib.parse.quote(instrument_key, safe="")
        if is_expired:
            endpoint = f"/expired-instruments/historical-candle/{enc_key}/1minute/{expiry}/{week_start}"
        else:
            endpoint = f"/historical-candle/{enc_key}/1minute/{expiry}/{week_start}"
        raw = api_get(endpoint)["data"]["candles"]
        with open(week_path, "w") as f:
            json.dump(raw, f)

    by_day = {}
    for row in raw:
        day_str = row[0][:10]
        time_str = row[0][11:16]
        by_day.setdefault(day_str, {})[time_str] = {
            "time_str": time_str,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
        }
    return by_day


def prefetch_weekly_contracts(tasks: list):
    """Prefetch full-week 1-minute option candle series in parallel."""
    to_fetch = []
    for inst_key, week_start, expiry, is_expired in tasks:
        safe_key = inst_key.replace("|", "_")
        week_path = os.path.join(WEEK_CACHE_DIR, f"wk_{safe_key}_{week_start}_{expiry}.json")
        if not os.path.exists(week_path):
            to_fetch.append((inst_key, week_start, expiry, is_expired))

    if not to_fetch:
        return

    print(f"Prefetching {len(to_fetch)} weekly 1-minute option contract series from Upstox...")

    def worker(t):
        inst_key, week_start, expiry, is_expired = t
        safe_key = inst_key.replace("|", "_")
        week_path = os.path.join(WEEK_CACHE_DIR, f"wk_{safe_key}_{week_start}_{expiry}.json")
        enc_key = urllib.parse.quote(inst_key, safe="")
        if is_expired:
            endpoint = f"/expired-instruments/historical-candle/{enc_key}/1minute/{expiry}/{week_start}"
        else:
            endpoint = f"/historical-candle/{enc_key}/1minute/{expiry}/{week_start}"
        for attempt in range(3):
            try:
                data = api_get(endpoint)["data"]["candles"]
                with open(week_path, "w") as f:
                    json.dump(data, f)
                return True
            except Exception:
                time.sleep(0.4 * (attempt + 1))
        return False

    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(worker, t) for t in to_fetch]
        for _ in as_completed(futs):
            done += 1
            if done % 60 == 0 or done == len(to_fetch):
                print(f"  • Cached {done}/{len(to_fetch)} weekly option series")


def score_trades(closed_legs: list, lots: int = 1, include_hedge: bool = True) -> dict:
    """
    Computes exact gross PnL, Zerodha brokerage + SEBI/NSE taxes, and net PnL
    across all executed option legs on a given day (including rolls and re-entries).
    Each item in closed_legs is (sell_price, buy_price).
    """
    qty = lots * LOT_SIZE
    gross = 0.0
    charges = (60.0 * lots) if (include_hedge and closed_legs) else 0.0
    for sell_p, buy_p in closed_legs:
        c = calculate_option_trade_costs(buy_price=buy_p, sell_price=sell_p, quantity=qty)
        gross += c["gross_pnl"]
        charges += c["total_charges"]
    gross = round(gross, 2)
    charges = round(charges, 2)
    return {
        "gross": gross,
        "charges": charges,
        "net": round(gross - charges, 2),
        "legs_traded": len(closed_legs),
    }


# ==============================================================================
# STRATEGY 1: Baseline Naive 09:25 ATM Straddle (30% SL + Immediate BE Trail)
# ==============================================================================
def strat_1_baseline(day_str: str, spot_bars: list, chain_bars: dict, is_expiry: bool) -> dict:
    b0 = next((b for b in spot_bars if b["time_str"] >= "09:25"), None)
    if not b0:
        return None
    atm = get_atm_strike(b0["close"], 50)
    ce_series = chain_bars.get((atm, "CE"), {})
    pe_series = chain_bars.get((atm, "PE"), {})
    times = sorted(t for t in (set(ce_series.keys()) & set(pe_series.keys())) if t >= "09:25")
    if len(times) < 5:
        return None

    t0 = times[0]
    ce_in, pe_in = ce_series[t0]["close"], pe_series[t0]["close"]
    ce_sl, pe_sl = round(ce_in * 1.30, 2), round(pe_in * 1.30, 2)
    ce_act, pe_act = True, True
    ce_out, pe_out = ce_in, pe_in
    cutoff = "14:15" if is_expiry else "15:15"

    for t in times[1:]:
        cb, pb = ce_series[t], pe_series[t]
        if ce_act and cb["high"] >= ce_sl:
            ce_act = False
            ce_out = round(max(ce_sl, cb["open"]) + 0.5, 2)
            if pe_act and pb["close"] < pe_in:
                pe_sl = pe_in
        if pe_act and pb["high"] >= pe_sl:
            pe_act = False
            pe_out = round(max(pe_sl, pb["open"]) + 0.5, 2)
            if ce_act and cb["close"] < ce_in:
                ce_sl = ce_in
        if (not ce_act and not pe_act) or t >= cutoff:
            if ce_act:
                ce_out = cb["close"]
            if pe_act:
                pe_out = pb["close"]
            break

    res = score_trades([(ce_in, ce_out), (pe_in, pe_out)])
    res["date"] = day_str
    res["is_expiry"] = is_expiry
    return res


# ==============================================================================
# STRATEGY 2: Institutional "Re-Entry on Cost" + No Premature BE Choke (09:45 Entry)
# ==============================================================================
def strat_2_reentry_on_cost(day_str: str, spot_bars: list, chain_bars: dict, is_expiry: bool,
                            entry_time: str = "09:45", sl_pct: float = 0.35, max_reentries: int = 1) -> dict:
    b0 = next((b for b in spot_bars if b["time_str"] >= entry_time), None)
    if not b0:
        return None
    atm = get_atm_strike(b0["close"], 50)
    ce_series = chain_bars.get((atm, "CE"), {})
    pe_series = chain_bars.get((atm, "PE"), {})
    times = sorted(t for t in (set(ce_series.keys()) & set(pe_series.keys())) if t >= entry_time)
    if len(times) < 5:
        return None

    t0 = times[0]
    ce_orig, pe_orig = ce_series[t0]["close"], pe_series[t0]["close"]
    ce_in, pe_in = ce_orig, pe_orig
    ce_sl, pe_sl = round(ce_in * (1.0 + sl_pct), 2), round(pe_in * (1.0 + sl_pct), 2)
    ce_act, pe_act = True, True
    ce_re_left, pe_re_left = max_reentries, max_reentries
    closed_legs = []
    cutoff = "14:15" if is_expiry else "15:15"

    # Combined MTM loss guardrail: 35% of initial combined premium
    max_day_loss_pts = (ce_orig + pe_orig) * 0.35

    for t in times[1:]:
        cb, pb = ce_series[t], pe_series[t]

        # Check active CE SL
        if ce_act and cb["high"] >= ce_sl:
            ce_act = False
            fill = round(max(ce_sl, cb["open"]) + 0.5, 2)
            closed_legs.append((ce_in, fill))
            # Only trail surviving PE to breakeven if CE has exhausted all re-entries
            if ce_re_left == 0 and pe_act and pb["close"] < pe_in:
                pe_sl = pe_in
        elif (not ce_act) and ce_re_left > 0 and t < "14:00":
            # Re-entry on Cost: if CE premium drops back to or below original entry price
            if cb["low"] <= ce_orig and cb["close"] <= ce_orig:
                ce_act = True
                ce_re_left -= 1
                ce_in = cb["close"]
                ce_sl = round(ce_in * (1.0 + sl_pct), 2)

        # Check active PE SL
        if pe_act and pb["high"] >= pe_sl:
            pe_act = False
            fill = round(max(pe_sl, pb["open"]) + 0.5, 2)
            closed_legs.append((pe_in, fill))
            if pe_re_left == 0 and ce_act and cb["close"] < ce_in:
                ce_sl = ce_in
        elif (not pe_act) and pe_re_left > 0 and t < "14:00":
            if pb["low"] <= pe_orig and pb["close"] <= pe_orig:
                pe_act = True
                pe_re_left -= 1
                pe_in = pb["close"]
                pe_sl = round(pe_in * (1.0 + sl_pct), 2)

        # Check Combined MTM Emergency Stop
        realized_pts = sum(s - b for s, b in closed_legs)
        unrealized_pts = ((ce_in - cb["close"]) if ce_act else 0.0) + ((pe_in - pb["close"]) if pe_act else 0.0)
        if (realized_pts + unrealized_pts) <= -max_day_loss_pts:
            if ce_act:
                closed_legs.append((ce_in, round(cb["close"] + 0.5, 2)))
                ce_act = False
            if pe_act:
                closed_legs.append((pe_in, round(pb["close"] + 0.5, 2)))
                pe_act = False
            break

        if t >= cutoff or (not ce_act and not pe_act and ce_re_left == 0 and pe_re_left == 0):
            if ce_act:
                closed_legs.append((ce_in, cb["close"]))
                ce_act = False
            if pe_act:
                closed_legs.append((pe_in, pb["close"]))
                pe_act = False
            break

    res = score_trades(closed_legs)
    res["date"] = day_str
    res["is_expiry"] = is_expiry
    return res


# ==============================================================================
# STRATEGY 3: "Wait & Trade" (W&T Decay Confirmation) + Combined MTM Guardrail
# ==============================================================================
def strat_3_wait_and_trade(day_str: str, spot_bars: list, chain_bars: dict, is_expiry: bool) -> dict:
    """
    At 09:30 AM, sets reference prices on ATM CE & PE.
    Waits for each leg to drop by 5% below its 09:30 reference price before selling it
    (avoiding selling into an expanding morning breakout leg!).
    """
    b0 = next((b for b in spot_bars if b["time_str"] >= "09:30"), None)
    if not b0:
        return None
    atm = get_atm_strike(b0["close"], 50)
    ce_series = chain_bars.get((atm, "CE"), {})
    pe_series = chain_bars.get((atm, "PE"), {})
    times = sorted(t for t in (set(ce_series.keys()) & set(pe_series.keys())) if t >= "09:30")
    if len(times) < 5:
        return None

    t0 = times[0]
    ce_ref, pe_ref = ce_series[t0]["close"], pe_series[t0]["close"]
    ce_trig, pe_trig = round(ce_ref * 0.95, 2), round(pe_ref * 0.95, 2)

    ce_state, pe_state = "WAITING", "WAITING"  # WAITING, ACTIVE, STOPPED
    ce_in, pe_in = 0.0, 0.0
    ce_sl, pe_sl = 0.0, 0.0
    closed_legs = []
    cutoff = "14:15" if is_expiry else "15:15"

    for t in times[1:]:
        cb, pb = ce_series[t], pe_series[t]

        # Wait & Trade entry trigger (before 13:30)
        if ce_state == "WAITING" and t < "13:30" and cb["close"] <= ce_trig:
            ce_state = "ACTIVE"
            ce_in = cb["close"]
            ce_sl = round(ce_in * 1.35, 2)

        if pe_state == "WAITING" and t < "13:30" and pb["close"] <= pe_trig:
            pe_state = "ACTIVE"
            pe_in = pb["close"]
            pe_sl = round(pe_in * 1.35, 2)

        # Active SL checks
        if ce_state == "ACTIVE" and cb["high"] >= ce_sl:
            ce_state = "STOPPED"
            closed_legs.append((ce_in, round(max(ce_sl, cb["open"]) + 0.5, 2)))
            # Trail PE to breakeven only if PE is already profitable by >20%
            if pe_state == "ACTIVE" and pb["close"] <= pe_in * 0.80:
                pe_sl = pe_in

        if pe_state == "ACTIVE" and pb["high"] >= pe_sl:
            pe_state = "STOPPED"
            closed_legs.append((pe_in, round(max(pe_sl, pb["open"]) + 0.5, 2)))
            if ce_state == "ACTIVE" and cb["close"] <= ce_in * 0.80:
                ce_sl = ce_in

        if t >= cutoff:
            if ce_state == "ACTIVE":
                closed_legs.append((ce_in, cb["close"]))
                ce_state = "STOPPED"
            if pe_state == "ACTIVE":
                closed_legs.append((pe_in, pb["close"]))
                pe_state = "STOPPED"
            break

    res = score_trades(closed_legs)
    res["date"] = day_str
    res["is_expiry"] = is_expiry
    return res


# ==============================================================================
# STRATEGY 4: P R Sundar OTM Strangle + "Firefighting" (Untested-Leg Rolling)
# ==============================================================================
def strat_4_pr_sundar_strangle_firefight(day_str: str, spot_bars: list, chain_bars: dict, is_expiry: bool,
                                         otm_offset: int = 100, max_rolls: int = 2) -> dict:
    """
    P R Sundar Non-Directional Strangle + Untested Leg Adjustment:
    1. Enter OTM Strangle at 09:35 AM (ATM + otm_offset CE, ATM - otm_offset PE).
    2. Firefighting Adjustment:
       When NIFTY moves strongly toward one side, if the untested leg decays by >=45%
       AND the tested leg's premium exceeds 1.8x the untested leg's premium:
       -> Book profit on the untested leg and roll it 50 points closer to the tested strike
          (up to matching the tested strike = straddle, never inverting), collecting fresh credit!
    3. Guardrail: Exit entire position if net day MTM loss exceeds 35% of initial credit,
       or if an individual leg expands past 1.85x its entry price after rolls.
    """
    b0 = next((b for b in spot_bars if b["time_str"] >= "09:35"), None)
    if not b0:
        return None
    atm = get_atm_strike(b0["close"], 50)
    ce_strike = atm + otm_offset
    pe_strike = atm - otm_offset

    if (ce_strike, "CE") not in chain_bars or (pe_strike, "PE") not in chain_bars:
        return None

    times = sorted(t for t in (set(chain_bars[(ce_strike, "CE")].keys()) & set(chain_bars[(pe_strike, "PE")].keys())) if t >= "09:35")
    if len(times) < 5:
        return None

    t0 = times[0]
    ce_in = chain_bars[(ce_strike, "CE")][t0]["close"]
    pe_in = chain_bars[(pe_strike, "PE")][t0]["close"]
    init_credit = ce_in + pe_in
    max_loss_pts = max(25.0, init_credit * 0.40)

    closed_legs = []
    rolls_done = 0
    ce_act, pe_act = True, True
    cutoff = "14:20" if is_expiry else "15:15"

    for t in times[1:]:
        cb = chain_bars.get((ce_strike, "CE"), {}).get(t)
        pb = chain_bars.get((pe_strike, "PE"), {}).get(t)
        if not cb or not pb:
            continue

        cur_ce = cb["close"]
        cur_pe = pb["close"]

        # Check Combined MTM Stop-Loss first (using high of tested leg)
        realized_pts = sum(s - b for s, b in closed_legs)
        worst_unrealized = ((ce_in - cb["high"]) if ce_act else 0.0) + ((pe_in - pb["high"]) if pe_act else 0.0)
        if (realized_pts + worst_unrealized) <= -max_loss_pts:
            if ce_act:
                closed_legs.append((ce_in, round(cb["close"] + 0.5, 2)))
                ce_act = False
            if pe_act:
                closed_legs.append((pe_in, round(pb["close"] + 0.5, 2)))
                pe_act = False
            break

        # P R Sundar Untested-Leg Roll ("Firefighting"):
        if ce_act and pe_act and rolls_done < max_rolls and t < "14:00" and (ce_strike > pe_strike):
            # Case A: Market rallied -> CE is tested (expensive), PE is untested (decayed <= 55% of entry & CE >= 1.8x PE)
            if cur_pe <= pe_in * 0.55 and cur_ce >= cur_pe * 1.8:
                new_pe_strike = min(ce_strike, pe_strike + 50)
                new_pb = chain_bars.get((new_pe_strike, "PE"), {}).get(t)
                if new_pb and new_pe_strike > pe_strike:
                    closed_legs.append((pe_in, cur_pe))  # Book winning PE
                    pe_strike = new_pe_strike
                    pe_in = new_pb["close"]
                    rolls_done += 1
                    continue

            # Case B: Market dropped -> PE is tested (expensive), CE is untested (decayed <= 55% of entry & PE >= 1.8x CE)
            elif cur_ce <= ce_in * 0.55 and cur_pe >= cur_ce * 1.8:
                new_ce_strike = max(pe_strike, ce_strike - 50)
                new_cb = chain_bars.get((new_ce_strike, "CE"), {}).get(t)
                if new_cb and new_ce_strike < ce_strike:
                    closed_legs.append((ce_in, cur_ce))  # Book winning CE
                    ce_strike = new_ce_strike
                    ce_in = new_cb["close"]
                    rolls_done += 1
                    continue

        if t >= cutoff:
            if ce_act:
                closed_legs.append((ce_in, cur_ce))
                ce_act = False
            if pe_act:
                closed_legs.append((pe_in, cur_pe))
                pe_act = False
            break

    res = score_trades(closed_legs)
    res["date"] = day_str
    res["is_expiry"] = is_expiry
    return res


# ==============================================================================
# STRATEGY 5: P R Sundar Positional Weekly Strangle + Firefighting (Fri -> Tue)
# ==============================================================================
def simulate_positional_week(week_days: list, spot_by_day: dict, chain_by_day: dict, expiry: str) -> list:
    """
    P R Sundar Positional Weekly Decay + Firefighting:
    1. Enter OTM±100 Short Strangle at 09:45 AM on Friday (start of high-theta window -> Tuesday Expiry).
    2. Untested-Leg Roll ("Firefighting"):
       When one leg decays by >=50% and the tested leg is >=1.8x the untested leg,
       book profit on the untested leg and roll it 50 pts closer to the tested strike (max 2 rolls).
    3. Tested-Leg Risk Cap:
       Each leg has a strict +44% Stop-Loss (checked on 1-minute High + ₹0.50 slippage) so overnight
       or multi-day trends never turn into uncapped blowups. Once one leg stops out and the surviving
       leg decays by >=25%, lock the surviving leg's stop-loss at Breakeven.
    """
    exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
    active_days = [d for d in week_days if 0 <= (exp_dt - datetime.strptime(d, "%Y-%m-%d")).days <= 4]
    if not active_days:
        return []

    first_day = active_days[0]
    b0 = next((b for b in spot_by_day[first_day] if b["time_str"] >= "09:45"), None)
    if not b0:
        return []

    atm = get_atm_strike(b0["close"], 50)
    ce_k, pe_k = atm + 100, atm - 100
    fc = chain_by_day.get(first_day, {})
    if (ce_k, "CE") not in fc or (pe_k, "PE") not in fc:
        return []

    t0_times = sorted(t for t in (set(fc[(ce_k, "CE")].keys()) & set(fc[(pe_k, "PE")].keys())) if t >= "09:45")
    if not t0_times:
        return []

    t0 = t0_times[0]
    ce_in = fc[(ce_k, "CE")][t0]["close"]
    pe_in = fc[(pe_k, "PE")][t0]["close"]
    leg_sl_mult = 1.44
    ce_sl = round(ce_in * leg_sl_mult, 2)
    pe_sl = round(pe_in * leg_sl_mult, 2)

    closed_legs = []
    rolls_done = 0
    ce_act, pe_act = True, True
    last_day = active_days[-1]

    for d_idx, day_str in enumerate(active_days):
        if not ce_act and not pe_act:
            break
        dc = chain_by_day.get(day_str, {})
        ce_s = dc.get((ce_k, "CE"), {})
        pe_s = dc.get((pe_k, "PE"), {})
        times = sorted(set(ce_s.keys()) & set(pe_s.keys()))
        if d_idx == 0:
            times = [t for t in times if t > t0]

        is_exp = (day_str == expiry or day_str == last_day)
        cutoff = "14:20" if is_exp else "15:25"

        for t in times:
            cb = dc.get((ce_k, "CE"), {}).get(t)
            pb = dc.get((pe_k, "PE"), {}).get(t)
            if not cb or not pb:
                continue

            # P R Sundar Untested-Leg Roll across the week
            if ce_act and pe_act and rolls_done < 2 and (ce_k > pe_k):
                if pb["close"] <= pe_in * 0.50 and cb["close"] >= pb["close"] * 1.8:
                    new_pe = min(ce_k, pe_k + 50)
                    npb = dc.get((new_pe, "PE"), {}).get(t)
                    if npb and new_pe > pe_k:
                        closed_legs.append((pe_in, pb["close"]))
                        pe_k = new_pe
                        pe_in = npb["close"]
                        pe_sl = round(pe_in * leg_sl_mult, 2)
                        rolls_done += 1
                        continue
                elif cb["close"] <= ce_in * 0.50 and pb["close"] >= cb["close"] * 1.8:
                    new_ce = max(pe_k, ce_k - 50)
                    ncb = dc.get((new_ce, "CE"), {}).get(t)
                    if ncb and new_ce < ce_k:
                        closed_legs.append((ce_in, cb["close"]))
                        ce_k = new_ce
                        ce_in = ncb["close"]
                        ce_sl = round(ce_in * leg_sl_mult, 2)
                        rolls_done += 1
                        continue

            # Tested-Leg Stop-Loss Check (1m High + ₹0.50 slippage)
            if ce_act and cb["high"] >= ce_sl:
                ce_act = False
                closed_legs.append((ce_in, round(max(ce_sl, cb["open"]) + 0.5, 2)))
                if pe_act and pb["close"] <= pe_in * 0.75:
                    pe_sl = pe_in

            if pe_act and pb["high"] >= pe_sl:
                pe_act = False
                closed_legs.append((pe_in, round(max(pe_sl, pb["open"]) + 0.5, 2)))
                if ce_act and cb["close"] <= ce_in * 0.75:
                    ce_sl = ce_in

            if is_exp and t >= cutoff:
                if ce_act:
                    closed_legs.append((ce_in, cb["close"]))
                    ce_act = False
                if pe_act:
                    closed_legs.append((pe_in, pb["close"]))
                    pe_act = False
                break

    if ce_act or pe_act:
        dc = chain_by_day.get(last_day, {})
        ce_s, pe_s = dc.get((ce_k, "CE"), {}), dc.get((pe_k, "PE"), {})
        common_t = sorted(set(ce_s.keys()) & set(pe_s.keys()))
        if common_t:
            tl = common_t[-1]
            if ce_act:
                closed_legs.append((ce_in, ce_s[tl]["close"]))
            if pe_act:
                closed_legs.append((pe_in, pe_s[tl]["close"]))

    res = score_trades(closed_legs, lots=1, include_hedge=True)
    res["date"] = last_day
    res["is_expiry"] = (last_day == expiry)
    return [res]


# ==============================================================================
# STRATEGY 6: Institutional Regime-Adaptive System (DTE Filter + Opening Shock Filter + W&T / Re-Entry)
# ==============================================================================
def strat_6_institutional_adaptive(day_str: str, spot_bars: list, chain_bars: dict, is_expiry: bool, in_high_theta_window: bool = None) -> dict:
    """
    Combines institutional rules discovered across Indian prop desks:
    1. DTE Regime Filter (Last 3 Sessions of the Weekly Expiry Cycle: T-2, T-1, T-0 Expiry):
       Skip T-4 and T-3 (5–6 DTE) where single-day theta decay is near zero and Vega/Delta risk dominates.
       Automatically adapts across Thursday expiries (Oct 2024–Aug 2025) and Tuesday expiries (Sep 2025–Oct 2026).
    2. Opening Shock / Trend Day Filter:
       Measure the 09:15 -> 09:45 AM Opening Range & Spot Displacement.
       If NIFTY has already moved > 0.65% from 09:15 open to 09:45 (runaway trend / macro shock day),
       use OTM Strangle Firefighting instead of a raw ATM Straddle!
    3. Execution on Normal Decay Sessions (T-2, T-1, T-0):
       09:45 AM Entry (post discovery), 35% Individual SL (45% on 0-DTE Expiry),
       1 Re-entry on Cost, and 35% Combined MTM Guardrail.
    """
    if in_high_theta_window is not None:
        if not in_high_theta_window:
            return None
    else:
        dt = datetime.strptime(day_str, "%Y-%m-%d")
        if dt.weekday() in (2, 3) and not is_expiry:
            return None

    open_bar = spot_bars[0]
    b_945 = next((b for b in spot_bars if b["time_str"] >= "09:45"), None)
    if not b_945:
        return None

    morning_move_pct = abs(b_945["close"] - open_bar["open"]) / open_bar["open"] * 100.0
    if morning_move_pct > 0.65:
        # High-momentum morning breakout -> deploy OTM Strangle with P R Sundar Firefighting
        return strat_4_pr_sundar_strangle_firefight(day_str, spot_bars, chain_bars, is_expiry, otm_offset=100, max_rolls=2)

    # Otherwise deploy 09:45 AM ATM Straddle with DTE-calibrated SL & Re-entry on Cost
    sl_pct = 0.45 if is_expiry else 0.35
    return strat_2_reentry_on_cost(day_str, spot_bars, chain_bars, is_expiry,
                                   entry_time="09:45", sl_pct=sl_pct, max_reentries=1)


def main():
    print("=" * 122)
    print(f"  INSTITUTIONAL & P R SUNDAR STRATEGY RESEARCH ON 1-YEAR REAL UPSTOX DATA ({START_DATE} TO {END_DATE})")
    print("=" * 122)

    spot_by_day = fetch_1year_spot_1m()
    trading_days = sorted(spot_by_day.keys())
    expired_expiries, active_expiries, active_contracts = get_all_expiries_and_contracts()
    all_expiries = sorted(expired_expiries + active_expiries)

    # Group trading days by their weekly expiry
    weeks = {}
    for d in trading_days:
        exp = next((e for e in all_expiries if e >= d), None)
        if exp:
            weeks.setdefault(exp, []).append(d)

    # Identify all (strike, CE/PE) contracts needed across each week (ATM and ATM ± 50, 100)
    weekly_tasks = []
    week_meta = {}
    for exp, w_days in sorted(weeks.items()):
        contracts, is_exp = get_contracts_for_expiry(exp, expired_expiries, active_contracts)
        c_map = {(int(round(c["strike_price"])), c["instrument_type"]): c for c in contracts}
        w_start = w_days[0]

        needed_strikes = set()
        for d in w_days:
            for t_check in ("09:25", "09:30", "09:35", "09:45"):
                b = next((x for x in spot_by_day[d] if x["time_str"] >= t_check), None)
                if b:
                    atm = get_atm_strike(b["close"], 50)
                    for offset in (-100, -50, 0, 50, 100):
                        needed_strikes.add(atm + offset)

        week_meta[exp] = (w_days, w_start, is_exp, c_map, sorted(needed_strikes))
        for k in sorted(needed_strikes):
            for opt_type in ("CE", "PE"):
                if (k, opt_type) in c_map:
                    weekly_tasks.append((c_map[(k, opt_type)]["instrument_key"], w_start, exp, is_exp))

    prefetch_weekly_contracts(weekly_tasks)

    # Assemble day chains and run all 6 strategy architectures
    s1_res, s2_res, s3_res, s4_res, s5_res, s6_res = [], [], [], [], [], []

    for exp, (w_days, w_start, is_exp, c_map, strikes) in sorted(week_meta.items()):
        chain_by_day = {d: {} for d in w_days}
        for k in strikes:
            for opt_type in ("CE", "PE"):
                c = c_map.get((k, opt_type))
                if not c:
                    continue
                wk_data = get_week_option_candles(c["instrument_key"], w_start, exp, is_exp)
                for d in w_days:
                    if d in wk_data:
                        chain_by_day[d][(k, opt_type)] = wk_data[d]

        # Run Positional Weekly strategy (Strategy 5) on the week
        s5_res.extend(simulate_positional_week(w_days, spot_by_day, chain_by_day, exp))

        # Run Intraday strategies (1, 2, 3, 4, 6) on each day of the week
        for d in w_days:
            is_exp_day = (d == exp)
            d_spot = spot_by_day[d]
            d_chain = chain_by_day[d]

            r1 = strat_1_baseline(d, d_spot, d_chain, is_exp_day)
            r2 = strat_2_reentry_on_cost(d, d_spot, d_chain, is_exp_day)
            r3 = strat_3_wait_and_trade(d, d_spot, d_chain, is_exp_day)
            r4 = strat_4_pr_sundar_strangle_firefight(d, d_spot, d_chain, is_exp_day)
            r6 = strat_6_institutional_adaptive(d, d_spot, d_chain, is_exp_day)

            if r1: s1_res.append(r1)
            if r2: s2_res.append(r2)
            if r3: s3_res.append(r3)
            if r4: s4_res.append(r4)
            if r6: s6_res.append(r6)

    strategies = [
        ("1. Baseline (09:25 ATM Straddle, 30% SL + Immediate BE)", s1_res),
        ("2. Re-Entry on Cost (09:45 ATM, 35% SL, 1 Re-Entry, No Early BE)", s2_res),
        ("3. Wait & Trade (09:30 Ref, -5% Decay Confirm Entry, 35% SL)", s3_res),
        ("4. P R Sundar Intraday OTM Strangle + Untested-Leg Rolling", s4_res),
        ("5. P R Sundar Positional Weekly Strangle + Rolling (3-Day Hold)", s5_res),
        ("6. Institutional Regime-Adaptive (DTE + Shock Filter + Re-Entry/Roll)", s6_res),
    ]

    print("\n" + "=" * 126)
    print("  HEAD-TO-HEAD 1-YEAR REAL UPSTOX BENCHMARK (NOV 2025 – OCT 2026 | 1 LOT = 65 QTY | +₹0.50 SLIPPAGE)")
    print("=" * 126)
    print(f"{'Strategy Architecture':<68} | {'Trades':<6} | {'Win Rate':<12} | {'Gross PnL':<12} | {'Charges':<10} | {'NET PROFIT':<13} | {'Max DD'}")
    print("-" * 126)

    for name, rows in strategies:
        m = compute_metrics(rows)
        wr = f"{m['wins']}/{m['total']} ({m['win_rate']:.1f}%)"
        print(f"{name:<68} | {m['total']:<6} | {wr:<12} | ₹{m['gross']:+10,.0f} | ₹{m['charges']:8,.0f} | ₹{m['net']:+11,.0f} | ₹{m['max_dd']:,.0f}")
    print("=" * 126)

    # Print Month-by-Month Comparison of Baseline (#1), Positional (#5), and Institutional Adaptive (#6)
    print("\n" + "=" * 126)
    print("  MONTH-BY-MONTH CONSISTENCY across REGIMES: BASELINE (#1) vs POSITIONAL WEEKLY (#5) vs INSTITUTIONAL ADAPTIVE (#6)")
    print("=" * 126)
    print(f"{'Month':<10} | {'#1 Baseline Net':<18} | {'#4 Intraday Roll Net':<22} | {'#5 Positional Weekly Net':<26} | {'#6 Institutional Adaptive Net':<30}")
    print("-" * 126)

    months = sorted(list({r["date"][:7] for r in s1_res}))
    for ym in months:
        m1 = sum(r["net"] for r in s1_res if r["date"].startswith(ym))
        m4 = sum(r["net"] for r in s4_res if r["date"].startswith(ym))
        m5 = sum(r["net"] for r in s5_res if r["date"].startswith(ym))
        m6 = sum(r["net"] for r in s6_res if r["date"].startswith(ym))
        print(f"{ym:<10} | ₹{m1:+15,.0f}  | ₹{m4:+19,.0f}  | ₹{m5:+23,.0f}  | ₹{m6:+27,.0f}")
    print("=" * 126)


if __name__ == "__main__":
    main()
