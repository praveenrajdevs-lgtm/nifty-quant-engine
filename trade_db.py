"""
Trade Persistence Engine (SQLite)
Stores real-time paper trades, live active position state, order executions, daily PnL, and audit logs.
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS live_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        state TEXT,
        trade_date TEXT,
        atm_strike INTEGER,
        spot_entry REAL,
        current_spot REAL,
        ce_entry REAL,
        curr_ce REAL,
        ce_sl REAL,
        ce_status TEXT,
        pe_entry REAL,
        curr_pe REAL,
        pe_sl REAL,
        pe_status TEXT,
        unrealized_pnl REAL,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def update_live_state(data: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
    INSERT OR REPLACE INTO live_state (
        id, state, trade_date, atm_strike, spot_entry, current_spot,
        ce_entry, curr_ce, ce_sl, ce_status,
        pe_entry, curr_pe, pe_sl, pe_status,
        unrealized_pnl, updated_at
    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["state"], data["trade_date"], data["atm_strike"], data["spot_entry"], data["current_spot"],
        data["ce_entry"], data["curr_ce"], data["ce_sl"], data["ce_status"],
        data["pe_entry"], data["curr_pe"], data["pe_sl"], data["pe_status"],
        data["unrealized_pnl"], now_str
    ))
    conn.commit()
    conn.close()

def get_live_state():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    SELECT state, trade_date, atm_strike, spot_entry, current_spot,
           ce_entry, curr_ce, ce_sl, ce_status,
           pe_entry, curr_pe, pe_sl, pe_status,
           unrealized_pnl, updated_at
    FROM live_state WHERE id = 1
    """)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "state": row[0],
        "trade_date": row[1],
        "atm_strike": row[2],
        "spot_entry": row[3],
        "current_spot": row[4],
        "ce_entry": row[5],
        "curr_ce": row[6],
        "ce_sl": row[7],
        "ce_status": row[8],
        "pe_entry": row[9],
        "curr_pe": row[10],
        "pe_sl": row[11],
        "pe_status": row[12],
        "unrealized_pnl": row[13],
        "updated_at": row[14]
    }

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
