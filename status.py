"""
System Status & Trade Journal CLI
Run anytime to see current daemon state, open trades, SQLite history, and P&L.
"""
import sqlite3
import os
from datetime import datetime
from trade_db import DB_PATH, get_performance_summary
from live_feed import get_live_nifty_spot

def show_status():
    print("=" * 85)
    print("  AUTONOMOUS INSTITUTIONAL TRADING SYSTEM: STATUS DASHBOARD")
    print(f"  System Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    live_spot = get_live_nifty_spot()
    print(f"  Live NIFTY 50 Spot : {live_spot:.2f}")
    print("=" * 85)

    # 1. Performance Summary from Database
    stats = get_performance_summary()
    print("ALL-TIME SQLite PERFORMANCE AUDIT:")
    print(f"  • Total Days Logged    : {stats['total_trades']}")
    print(f"  • Winning Days         : {stats['wins']} | Losing Days: {stats['losses']}")
    print(f"  • Win Rate             : {stats['win_rate']}%")
    print(f"  • Gross Profit         : ₹{stats['gross_pnl']:+,.2f}")
    print(f"  • Taxes & Fees Deducted: ₹{stats['charges']:,.2f}")
    print(f"  • NET IN-POCKET CASH   : ₹{stats['net_pnl']:+,.2f}")
    print("-" * 85)

    # 2. Recent 5 Trades Journal
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    SELECT trade_date, atm_strike, ce_status, pe_status, gross_pnl, charges, net_pnl
    FROM daily_trades ORDER BY id DESC LIMIT 5
    """)
    rows = cur.fetchall()
    conn.close()

    if rows:
        print("RECENT TRADE JOURNAL ENTRIES:")
        print(f"{'Date':<12} | {'ATM Strike':<11} | {'CE Leg':<18} | {'PE Leg':<20} | {'Net P&L':<12}")
        print("-" * 85)
        for r in rows:
            net_str = f"₹{r[6]:+,.2f}"
            print(f"{r[0]:<12} | {r[1]:<11} | {r[2]:<18} | {r[3]:<20} | {net_str:<12}")
    else:
        print("No trades logged yet in the live database.")

    print("=" * 85)

if __name__ == "__main__":
    show_status()
