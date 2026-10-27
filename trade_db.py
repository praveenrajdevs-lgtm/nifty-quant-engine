"""
Trade Persistence Engine (SQLite)
Stores real-time paper trades, order executions, daily PnL, and audit logs.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "paper_trades.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date TEXT UNIQUE,
        symbol TEXT,
        atm_strike INTEGER,
        spot_entry REAL,
        ce_entry_prem REAL,
        pe_entry_prem REAL,
        ce_exit_prem REAL,
        pe_exit_prem REAL,
        ce_status TEXT,
        pe_status TEXT,
        lots INTEGER,
        gross_pnl REAL,
        charges REAL,
        net_pnl REAL,
        entry_time TEXT,
        exit_time TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        action TEXT,
        message TEXT,
        spot_price REAL
    )
    """)
    conn.commit()
    conn.close()

def log_audit(action: str, message: str, spot_price: float = 0.0):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO order_audit_log (timestamp, action, message, spot_price) VALUES (?, ?, ?, ?)",
                (now_str, action, message, spot_price))
    conn.commit()
    conn.close()

def save_daily_trade(record: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO daily_trades (
        trade_date, symbol, atm_strike, spot_entry, ce_entry_prem, pe_entry_prem,
        ce_exit_prem, pe_exit_prem, ce_status, pe_status, lots, gross_pnl, charges, net_pnl,
        entry_time, exit_time
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record["trade_date"], record["symbol"], record["atm_strike"], record["spot_entry"],
        record["ce_entry_prem"], record["pe_entry_prem"], record["ce_exit_prem"], record["pe_exit_prem"],
        record["ce_status"], record["pe_status"], record["lots"], record["gross_pnl"], record["charges"],
        record["net_pnl"], record["entry_time"], record["exit_time"]
    ))
    conn.commit()
    conn.close()

def get_performance_summary():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(gross_pnl), SUM(charges), SUM(net_pnl) FROM daily_trades")
    row = cur.fetchone()
    total = row[0] or 0
    gross = row[1] or 0.0
    charges = row[2] or 0.0
    net = row[3] or 0.0

    cur.execute("SELECT COUNT(*) FROM daily_trades WHERE net_pnl > 0")
    wins = cur.fetchone()[0] or 0
    conn.close()

    win_rate = (wins / total * 100.0) if total > 0 else 0.0
    return {
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": round(win_rate, 1),
        "gross_pnl": round(gross, 2),
        "charges": round(charges, 2),
        "net_pnl": round(net, 2)
    }

init_db()
