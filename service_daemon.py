"""
Autonomous Background Trading Daemon (24/7 Autonomous Service)
Runs silently in the background:
- Wakes up every weekday (Mon-Fri) at 09:15 AM IST
- Checks opening shock & enters at 09:25 AM IST
- Streams live exchange ticks, manages 30% SL & Breakeven trails
- Squares off at 15:15 PM (14:15 PM on Thursday expiry)
- Saves audit logs and PnL to SQLite
- Sleeps overnight and resumes next morning automatically
"""
import time
import os
from datetime import datetime, timedelta
from paper_engine import PaperTradingDaemon
from live_feed import get_live_nifty_spot
from trade_db import log_audit, get_performance_summary

LOG_FILE = os.path.join(os.path.dirname(__file__), "daemon.log")

def log_event(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {message}"
    print(formatted)
    with open(LOG_FILE, "a") as f:
        f.write(formatted + "\n")

def run_service():
    log_event("=" * 80)
    log_event("AUTONOMOUS INSTITUTIONAL TRADING SYSTEM STARTED (DAEMON MODE)")
    log_event("=" * 80)

    last_traded_date = None

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            weekday = now.weekday()  # 0=Mon, ..., 4=Fri, 5=Sat, 6=Sun
            time_str = now.strftime("%H:%M")
            is_expiry = (weekday == 3)
            cutoff_time = "14:15" if is_expiry else "15:15"

            # 1. Skip Weekends
            if weekday >= 5:
                # Sleep until Monday 09:00 AM
                days_ahead = 7 - weekday
                next_mon = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0)
                wait_sec = max(60, int((next_mon - now).total_seconds()))
                log_event(f"Weekend detected. Daemon sleeping until Monday morning ({wait_sec//3600} hours)...")
                time.sleep(min(wait_sec, 3600))
                continue

            # 2. Before Market Open (Before 09:25 AM)
            if time_str < "09:25":
                wait_to_open = 30
                time.sleep(wait_to_open)
                continue

            # 3. Market Session Window (09:25 AM to Cutoff) - Execute ONCE per day
            if "09:25" <= time_str < cutoff_time and last_traded_date != today_str:
                log_event(f"Trading window open ({time_str}). Initializing session daemon...")
                daemon = PaperTradingDaemon(leg_sl_pct=0.30, lots=2)
                base_tte = 2.0 / 365.0

                # Initial entry at 09:25
                spot = get_live_nifty_spot()
                daemon.enter_straddle(spot, time_str)
                last_traded_date = today_str
                log_event(f"Entered Short Straddle at strike {daemon.atm_strike} on spot {spot:.2f}")

                # Monitor ticks every 5 seconds until square-off
                while daemon.state == "ENTERED":
                    now_tick = datetime.now()
                    tick_time = now_tick.strftime("%H:%M")
                    live_spot = get_live_nifty_spot()

                    mins_past_open = (now_tick.hour - 9) * 60 + (now_tick.minute - 15)
                    tte = max(0.0001, base_tte - (mins_past_open / (375.0 * 365.0)))

                    daemon.check_ticks(live_spot, tick_time, tte, is_expiry=is_expiry)

                    if tick_time >= cutoff_time or daemon.state == "SQUARED_OFF":
                        break

                    time.sleep(5)

                log_event("Intraday trading session concluded and saved to SQLite.")

            # 4. After Market Close (After 15:30 PM): Sleep overnight
            if time_str >= "15:30":
                tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=15, second=0)
                wait_sec = max(60, int((tomorrow - now).total_seconds()))
                log_event(f"Markets closed for today. Daemon sleeping overnight until 09:15 AM tomorrow ({wait_sec//3600}h {(wait_sec%3600)//60}m)...")
                time.sleep(min(wait_sec, 1800))
            else:
                time.sleep(60)

        except Exception as e:
            log_event(f"CRITICAL ERROR in daemon loop: {str(e)}. Auto-recovering in 15 seconds...")
            time.sleep(15)

if __name__ == "__main__":
    run_service()
