"""
Seeds the SQLite database with the verified 1-month intraday session records
so the web dashboard has complete live historical charts and metrics immediately.
"""
from test_1month_compounded import run_1month_compounded
from trade_db import save_daily_trade, init_db

def seed():
    init_db()
    res = run_1month_compounded(initial_capital=50000.0, capital_per_lot=35000.0, leg_sl_pct=0.30)
    for d in res["daily"]:
        record = {
            "trade_date": d["date"],
            "symbol": "NIFTY",
            "atm_strike": d["atm_strike"],
            "spot_entry": d["spot_entry"],
            "ce_entry_prem": d["ce_entry"],
            "pe_entry_prem": d["pe_entry"],
            "ce_exit_prem": d["ce_exit"],
            "pe_exit_prem": d["pe_exit"],
            "ce_status": d["ce_status"],
            "pe_status": d["pe_status"],
            "lots": d["lots"],
            "gross_pnl": d["gross"],
            "charges": d["charges"],
            "net_pnl": d["net"],
            "entry_time": f"{d['date']} 09:25:00",
            "exit_time": f"{d['date']} 15:15:00"
        }
        save_daily_trade(record)
    print(f"Successfully seeded {len(res['daily'])} trading sessions into paper_trades.db.")

if __name__ == "__main__":
    seed()
