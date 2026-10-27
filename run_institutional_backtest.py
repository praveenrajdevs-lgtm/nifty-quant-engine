"""
Multi-Month Institutional Quantitative Backtester (NIFTY & BANKNIFTY)
Tests 60 Days (3 Months) of 5-minute candles under real Zerodha & SEBI taxes.
"""
from data_feed import fetch_candles
from engine import run_backtest
from strategies_v2 import InstitutionalTrendATRStrategy

def evaluate_symbol(symbol: str = "NIFTY", range_period: str = "60d"):
    print("=" * 90)
    print(f"  INSTITUTIONAL QUANTITATIVE BACKTEST: {symbol} (5-Minute Timeframe, 60 Days)")
    print("=" * 90)
    
    candles = fetch_candles(symbol=symbol, interval="5m", range_period=range_period)
    print(f"Loaded {len(candles)} real 5-minute candles from {candles[0]['datetime']} to {candles[-1]['datetime']}.\n")

    strategies = [
        InstitutionalTrendATRStrategy(ema_period=50, channel_lookback=15, target_pts=20.0, stop_loss_pts=9.0, max_hold_bars=12),
        InstitutionalTrendATRStrategy(ema_period=50, channel_lookback=20, target_pts=25.0, stop_loss_pts=10.0, max_hold_bars=15),
        InstitutionalTrendATRStrategy(ema_period=30, channel_lookback=15, target_pts=22.0, stop_loss_pts=9.0, max_hold_bars=10),
    ]

    for strat in strategies:
        res = run_backtest(strat, candles, symbol=symbol, slippage_pts=0.5)
        print(f"\n>>> Strategy: {res['strategy_name']}")
        print(f"  • Total Trades: {res['total_trades']} | Wins: {res['wins']} | Losses: {res['losses']}")
        print(f"  • Win Rate: {res['win_rate_pct']}%")
        print(f"  • Gross P&L: ₹{res['gross_pnl']:+,.1f}")
        print(f"  • Total Taxes & Zerodha Brokerage: ₹{res['total_charges']:,.1f}")
        print(f"  • NET IN-POCKET P&L: ₹{res['net_pnl']:+,.1f}")
        print(f"  • Profit Factor: {res['profit_factor']}")
        print(f"  • Max Drawdown: ₹{res['max_drawdown']:,.1f}")

        # Monthly breakdown
        monthly = {}
        for t in res["trades"]:
            month = t.entry_time[:7]  # YYYY-MM
            monthly[month] = monthly.get(month, 0.0) + t.net_pnl

        print("  • Monthly Net Breakdown:")
        for m, pnl in sorted(monthly.items()):
            print(f"      {m}: ₹{pnl:+,.1f}")

def main():
    evaluate_symbol("NIFTY", "60d")
    print("\n" + "=" * 90 + "\n")
    evaluate_symbol("BANKNIFTY", "60d")

if __name__ == "__main__":
    main()
