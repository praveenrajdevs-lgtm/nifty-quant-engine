# Antigravity Quant Engine — NIFTY Options Trading & Backtesting System

A zero-dependency quantitative backtesting, simulation, and real-time paper-trading engine for **NSE NIFTY 50 & BANK NIFTY Options**, featuring a full Zerodha + SEBI transaction friction model and a live dark-mode web terminal.

## Key Features

- **Institutional 09:25 Short Straddle Daemon (`service_daemon.py` & `paper_engine.py`)**:
  - Automated entry at **09:25 AM IST** on the nearest ATM strike.
  - **30% Individual Leg Stop-Loss** with **Automatic Breakeven Trail** on the surviving leg to prevent double stop-loss whipsaws.
  - **Thursday Expiry Gamma Cutoff**: Early square-off at **14:15 PM IST** on Thursdays (`15:15 PM IST` on regular days).
- **Exact Zerodha & SEBI Friction Calculator (`friction.py`)**:
  - Accounts for ₹20/order brokerage, 0.1% STT on option sells, NSE exchange turnover charges, 18% GST, SEBI charges, stamp duty, and protective wing costs.
- **Pure-Python Black-Scholes Pricing Engine (`options_model.py`)**:
  - Computes theoretical Call/Put option premiums, Delta, and Theta decay dynamically without external C/Fortran dependencies.
- **Real-Time Web Dashboard (`web_server.py`)**:
  - Dark-mode web terminal served on `http://localhost:8080` with live NIFTY 50 spot polling, interactive SVG equity curve, active leg status, and SQLite audit ledger.

## Quick Start

### 1. Run the Real-Time Web Dashboard
```bash
python3 web_server.py
```
Then open **[http://localhost:8080](http://localhost:8080)** in your browser.

### 2. Run the 24/7 Autonomous Paper-Trading Daemon
```bash
python3 service_daemon.py
```

### 3. Check CLI Status Anytime
```bash
python3 status.py
```

### 4. Run Historical Backtests
```bash
# 1-Month Compounded Intraday Backtest (₹50,000 starting capital)
python3 test_1month_compounded.py

# 60-Day Adaptive Straddle with Opening Shock Filter
python3 adaptive_straddle.py

# 5-Year Multi-Regime Intraday Straddle Simulation
python3 run_5year_intraday_straddle.py
```
