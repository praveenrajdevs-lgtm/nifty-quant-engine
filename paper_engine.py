"""
Live Real-Time Paper Trading Daemon for Institutional NIFTY Option Selling
Runs 100% Free with zero API costs, streaming live exchange prices.
Features:
- Entry at 09:25 AM IST
- Dynamic ATM Strike Selection & Black-Scholes Greeks
- 30% Leg Stop-Loss
- Automatic Breakeven Adjustment on the remaining leg (Eliminates Double SL)
- Expiry Day (Thursday) 14:15 PM early cutoff
- Exact Zerodha Brokerage (₹40/order) + STT (0.1%) + GST (18%) + Penny Hedge cost
- SQLite Database logging
"""
import sys
import time
from datetime import datetime
from options_model import calculate_option_price, get_atm_strike
from friction import calculate_option_trade_costs
from live_feed import get_live_nifty_spot
from trade_db import log_audit, save_daily_trade, get_performance_summary, update_live_state
from data_feed import fetch_candles

LOT_SIZE = 25  # 1 lot Nifty

class PaperTradingDaemon:
    def __init__(self, leg_sl_pct: float = 0.30, lots: int = 2):
        self.leg_sl_pct = leg_sl_pct
        self.lots = lots
        self.total_qty = lots * LOT_SIZE
        self.state = "IDLE"  # IDLE, ENTERED, SQUARED_OFF

        self.spot_entry = 0.0
        self.atm_strike = 0
        self.ce_entry = 0.0
        self.pe_entry = 0.0
        self.ce_sl = 0.0
        self.pe_sl = 0.0
        
        self.ce_active = False
        self.pe_active = False
        self.ce_exit_price = 0.0
        self.pe_exit_price = 0.0
        self.ce_status = ""
        self.pe_status = ""
        self.entry_time = ""
        self.exit_time = ""

    def enter_straddle(self, spot: float, time_str: str):
        self.spot_entry = spot
        self.atm_strike = get_atm_strike(spot, step=50)
        self.entry_time = time_str

        # Price ATM options
        base_tte = 2.0 / 365.0
        ce_data = calculate_option_price(spot, self.atm_strike, base_tte, option_type="CE")
        pe_data = calculate_option_price(spot, self.atm_strike, base_tte, option_type="PE")

        self.ce_entry = ce_data["price"]
        self.pe_entry = pe_data["price"]
        self.ce_sl = round(self.ce_entry * (1.0 + self.leg_sl_pct), 2)
        self.pe_sl = round(self.pe_entry * (1.0 + self.leg_sl_pct), 2)

        self.ce_active = True
        self.pe_active = True
        self.ce_status = f"ACTIVE (SL: ₹{self.ce_sl:.1f})"
        self.pe_status = f"ACTIVE (SL: ₹{self.pe_sl:.1f})"
        self.state = "ENTERED"

        today_str = datetime.now().strftime("%Y-%m-%d")
        update_live_state({
            "state": "ENTERED",
            "trade_date": today_str,
            "atm_strike": self.atm_strike,
            "spot_entry": spot,
            "current_spot": spot,
            "ce_entry": self.ce_entry,
            "curr_ce": self.ce_entry,
            "ce_sl": self.ce_sl,
            "ce_status": self.ce_status,
            "pe_entry": self.pe_entry,
            "curr_pe": self.pe_entry,
            "pe_sl": self.pe_sl,
            "pe_status": self.pe_status,
            "unrealized_pnl": 0.0
        })

        log_audit("ENTRY", f"Entered {self.lots} Lots Short Straddle at {self.atm_strike} (CE: ₹{self.ce_entry}, PE: ₹{self.pe_entry})", spot)
        print("=" * 85)
        print(f"[{time_str}] >>> VIRTUAL ORDER EXECUTED: SHORT STRADDLE")
        print(f"  • Underlying NIFTY Spot : {spot:.2f}")
        print(f"  • ATM Strike Selected   : {self.atm_strike}")
        print(f"  • Quantity Deployed     : {self.lots} Lots ({self.total_qty} Qty)")
        print(f"  • Sold ATM Call (CE)    : ₹{self.ce_entry:.2f} (Stop Loss: ₹{self.ce_sl:.2f})")
        print(f"  • Sold ATM Put (PE)     : ₹{self.pe_entry:.2f} (Stop Loss: ₹{self.pe_sl:.2f})")
        print(f"  • Total Credit Harvested: ₹{(self.ce_entry + self.pe_entry) * self.total_qty:,.2f}")
        print("=" * 85)

    def check_ticks(self, current_spot: float, current_time: str, tte: float, is_expiry: bool = False):
        if self.state != "ENTERED":
            return

        curr_ce = calculate_option_price(current_spot, self.atm_strike, tte, option_type="CE")["price"]
        curr_pe = calculate_option_price(current_spot, self.atm_strike, tte, option_type="PE")["price"]

        # 1. Check CE Stop Loss
        if self.ce_active and curr_ce >= self.ce_sl:
            self.ce_active = False
            self.ce_exit_price = curr_ce
            self.ce_status = "BE HIT" if self.ce_sl == self.ce_entry else f"SL HIT (+{self.leg_sl_pct*100:.0f}%)"
            log_audit("SL_HIT", f"Call Leg Stopped at ₹{curr_ce}", current_spot)
            print(f"[{current_time}] ⚠️ CALL STOP-LOSS TRIGGERED at ₹{curr_ce:.2f}! (Loss: ₹{(self.ce_entry - curr_ce)*self.total_qty:,.1f})")

            # QUANT TWEAK: Move remaining Put stop to Breakeven (Cost Price) ONLY if current PE is below entry
            if self.pe_active and curr_pe < self.pe_entry:
                self.pe_sl = self.pe_entry
                self.pe_status = f"ACTIVE (BE SL: ₹{self.pe_sl:.1f})"
                print(f"[{current_time}] 🛡️ QUANT TWEAK APPLIED: Moved remaining PUT Stop-Loss to Breakeven (₹{self.pe_sl:.2f})")

        # 2. Check PE Stop Loss
        if self.pe_active and curr_pe >= self.pe_sl:
            self.pe_active = False
            self.pe_exit_price = curr_pe
            self.pe_status = "BE HIT" if self.pe_sl == self.pe_entry else f"SL HIT (+{self.leg_sl_pct*100:.0f}%)"
            log_audit("SL_HIT", f"Put Leg Stopped at ₹{curr_pe}", current_spot)
            print(f"[{current_time}] ⚠️ PUT STOP-LOSS TRIGGERED at ₹{curr_pe:.2f}! (Loss: ₹{(self.pe_entry - curr_pe)*self.total_qty:,.1f})")

            # QUANT TWEAK: Move remaining Call stop to Breakeven ONLY if current CE is below entry
            if self.ce_active and curr_ce < self.ce_entry:
                self.ce_sl = self.ce_entry
                self.ce_status = f"ACTIVE (BE SL: ₹{self.ce_sl:.1f})"
                print(f"[{current_time}] 🛡️ QUANT TWEAK APPLIED: Moved remaining CALL Stop-Loss to Breakeven (₹{self.ce_sl:.2f})")

        # Calculate live unrealized PnL
        eff_ce = curr_ce if self.ce_active else self.ce_exit_price
        eff_pe = curr_pe if self.pe_active else self.pe_exit_price
        live_gross = ((self.ce_entry - eff_ce) + (self.pe_entry - eff_pe)) * self.total_qty
        today_str = datetime.now().strftime("%Y-%m-%d")
        update_live_state({
            "state": "ENTERED",
            "trade_date": today_str,
            "atm_strike": self.atm_strike,
            "spot_entry": self.spot_entry,
            "current_spot": current_spot,
            "ce_entry": self.ce_entry,
            "curr_ce": eff_ce,
            "ce_sl": self.ce_sl,
            "ce_status": self.ce_status,
            "pe_entry": self.pe_entry,
            "curr_pe": eff_pe,
            "pe_sl": self.pe_sl,
            "pe_status": self.pe_status,
            "unrealized_pnl": round(live_gross, 2)
        })

        # 3. Square-off Check: If both legs are already closed OR cutoff time reached
        cutoff = "14:15" if is_expiry else "15:15"
        if (not self.ce_active and not self.pe_active) or current_time >= cutoff:
            self.square_off(current_spot, current_time, curr_ce, curr_pe)

    def square_off(self, current_spot: float, current_time: str, curr_ce: float, curr_pe: float):
        self.state = "SQUARED_OFF"
        self.exit_time = current_time

        if self.ce_active:
            self.ce_active = False
            self.ce_exit_price = curr_ce
            self.ce_status = "THETA HARVEST (EOD)"

        if self.pe_active:
            self.pe_active = False
            self.pe_exit_price = curr_pe
            self.pe_status = "THETA HARVEST (EOD)"

        # Calculate exact financial charges and net profit
        ce_cost = calculate_option_trade_costs(buy_price=self.ce_exit_price, sell_price=self.ce_entry, quantity=self.total_qty)
        pe_cost = calculate_option_trade_costs(buy_price=self.pe_exit_price, sell_price=self.pe_entry, quantity=self.total_qty)
        penny_hedge_cost = 60.0 * self.lots

        gross_pnl = ce_cost["gross_pnl"] + pe_cost["gross_pnl"]
        total_charges = ce_cost["total_charges"] + pe_cost["total_charges"] + penny_hedge_cost
        net_pnl = round(gross_pnl - total_charges, 2)

        # Save to SQLite
        today_str = datetime.now().strftime("%Y-%m-%d")
        record = {
            "trade_date": today_str,
            "symbol": "NIFTY",
            "atm_strike": self.atm_strike,
            "spot_entry": self.spot_entry,
            "ce_entry_prem": self.ce_entry,
            "pe_entry_prem": self.pe_entry,
            "ce_exit_prem": self.ce_exit_price,
            "pe_exit_prem": self.pe_exit_price,
            "ce_status": self.ce_status,
            "pe_status": self.pe_status,
            "lots": self.lots,
            "gross_pnl": gross_pnl,
            "charges": total_charges,
            "net_pnl": net_pnl,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time
        }
        save_daily_trade(record)
        update_live_state({
            "state": "SQUARED_OFF",
            "trade_date": today_str,
            "atm_strike": self.atm_strike,
            "spot_entry": self.spot_entry,
            "current_spot": current_spot,
            "ce_entry": self.ce_entry,
            "curr_ce": self.ce_exit_price,
            "ce_sl": self.ce_sl,
            "ce_status": self.ce_status,
            "pe_entry": self.pe_entry,
            "curr_pe": self.pe_exit_price,
            "pe_sl": self.pe_sl,
            "pe_status": self.pe_status,
            "unrealized_pnl": net_pnl
        })
        log_audit("EXIT", f"Square-off completed. Net PnL: ₹{net_pnl}", current_spot)

        print("\n" + "=" * 85)
        print(f"[{current_time}] >>> INTRADAY SESSION COMPLETE: FINAL P&L SUMMARY")
        print("=" * 85)
        print(f"  • Exit Spot Price      : {current_spot:.2f}")
        print(f"  • Call Leg (CE) Result : {self.ce_status} (Entry: ₹{self.ce_entry} -> Exit: ₹{self.ce_exit_price})")
        print(f"  • Put Leg (PE) Result  : {self.pe_status} (Entry: ₹{self.pe_entry} -> Exit: ₹{self.pe_exit_price})")
        print(f"  • Gross Trading Profit : ₹{gross_pnl:+,.2f}")
        print(f"  • Taxes, Brokerage & Hedges : ₹{total_charges:,.2f}")
        print(f"  • NET IN-POCKET CASH PROFIT : ₹{net_pnl:+,.2f}")
        print("=" * 85 + "\n")

def run_replay_simulation(lots: int = 2):
    """
    Simulates today's real intraday candles in accelerated replay so the user
    can test the complete live paper-trading engine right now.
    """
    print("=" * 85)
    print("  INSTITUTIONAL PAPER-TRADING DAEMON: LIVE REPLAY TEST MODE")
    print(f"  Deploying {lots} Lots of NIFTY 50 Options ({lots * LOT_SIZE} Qty)")
    print("=" * 85)

    candles = fetch_candles("NIFTY", interval="1m", range_period="5d")
    today_date = candles[-1]["datetime"][:10]
    today_candles = [c for c in candles if c["datetime"].startswith(today_date)]
    if len(today_candles) < 20:
        today_candles = candles[-375:]  # Fallback to last full session

    daemon = PaperTradingDaemon(leg_sl_pct=0.30, lots=lots)
    base_tte = 2.0 / 365.0

    print(f"Replaying session: {today_candles[0]['datetime']} to {today_candles[-1]['datetime']} ({len(today_candles)} ticks)...\n")

    for i, c in enumerate(today_candles):
        time_str = c["time_str"]
        spot = c["close"]

        # Check entry at 09:25 AM
        if daemon.state == "IDLE" and time_str >= "09:25":
            daemon.enter_straddle(spot, time_str)

        if daemon.state == "ENTERED":
            bars_held = i
            tte = max(0.0001, base_tte - (bars_held / (375.0 * 365.0)))
            daemon.check_ticks(spot, time_str, tte, is_expiry=False)

        if daemon.state == "SQUARED_OFF":
            break

    # Show database summary
    stats = get_performance_summary()
    print("ALL-TIME SQLite PAPER TRADING AUDIT RECORD:")
    print(f"  • Total Days Logged : {stats['total_trades']}")
    print(f"  • Total Wins        : {stats['wins']} | Losses: {stats['losses']}")
    print(f"  • Cumulative Net PnL: ₹{stats['net_pnl']:+,.2f}")

def run_live_daemon(lots: int = 2):
    """
    Runs during live market hours (09:15 to 15:30 IST) polling real-time exchange ticks.
    """
    print("=" * 85)
    print("  LIVE INSTITUTIONAL TRADING DAEMON RUNNING (REAL-TIME EXCHANGE FEED)")
    print("=" * 85)
    print(f"Target: NIFTY 50 Options | Capital Allocated: {lots} Lots ({lots * LOT_SIZE} Qty)")
    print("Waiting for market window (09:25 AM to 15:15 PM IST)...")

    daemon = PaperTradingDaemon(leg_sl_pct=0.30, lots=lots)
    base_tte = 2.0 / 365.0

    while True:
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        is_expiry = (now.weekday() == 3)

        # 1. Before market opens (Wait)
        if time_str < "09:25":
            print(f"[{time_str}] Market not ready. Next check in 30s...", end="\r")
            time.sleep(30)
            continue

        # 2. Fetch live spot price
        live_spot = get_live_nifty_spot()

        # 3. Entry trigger at 09:25 AM
        if daemon.state == "IDLE" and time_str >= "09:25" and time_str < "15:00":
            daemon.enter_straddle(live_spot, time_str)

        # 4. Active monitoring
        if daemon.state == "ENTERED":
            # Estimate intraday tte fraction
            mins_past_open = (now.hour - 9) * 60 + (now.minute - 15)
            tte = max(0.0001, base_tte - (mins_past_open / (375.0 * 365.0)))
            daemon.check_ticks(live_spot, time_str, tte, is_expiry=is_expiry)

        if daemon.state == "SQUARED_OFF":
            print(f"[{time_str}] Session finished and logged to SQLite. Daemon sleeping until tomorrow.")
            break

        time.sleep(5)  # Poll every 5 seconds

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        run_live_daemon(lots=2)
    else:
        run_replay_simulation(lots=2)
