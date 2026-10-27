"""
Multi-Strategy Quantitative Backtester & Analysis Runner
Executes multiple strategies across real NIFTY 50 intraday data.
"""
from data_feed import fetch_candles
from engine import run_backtest
from strategies import DemandSupplyReversalStrategy, VWAPBounceStrategy, FilteredKeyLevelStrategy

def main():
    print("=" * 80)
    print("  QUANTITATIVE OPTIONS SCALPING SIMULATOR (ZERODHA FRICTION MODEL)")
    print("=" * 80)
    print("Fetching real historical 1-minute intraday candles for NIFTY 50...")
    
    candles = fetch_candles(symbol="NIFTY", interval="1m", range_period="5d")
    print(f"Loaded {len(candles)} real 1-minute candles ({candles[0]['datetime']} to {candles[-1]['datetime']}).\n")

    strategies = [
        DemandSupplyReversalStrategy(lookback=20, target_pts=16.0, stop_loss_pts=8.0, max_hold_bars=15),
        DemandSupplyReversalStrategy(lookback=30, target_pts=20.0, stop_loss_pts=10.0, max_hold_bars=20),
        FilteredKeyLevelStrategy(lookback=60, target_pts=20.0, stop_loss_pts=9.0, max_trades_per_day=2),
        FilteredKeyLevelStrategy(lookback=45, target_pts=16.0, stop_loss_pts=8.0, max_trades_per_day=2),
    ]

    results = []
    for strat in strategies:
        res = run_backtest(strat, candles, symbol="NIFTY", slippage_pts=0.5)
        results.append(res)

    # Print Comparative Table
    print(f"{'Strategy Name':<45} | {'Trades':<6} | {'Win %':<6} | {'Gross PnL':<10} | {'Taxes/Fees':<10} | {'Net PnL':<10} | {'Max DD':<8}")
    print("-" * 105)
    for r in results:
        net_str = f"₹{r['net_pnl']:+,.1f}"
        gross_str = f"₹{r['gross_pnl']:+,.1f}"
        tax_str = f"₹{r['total_charges']:,.1f}"
        dd_str = f"₹{r['max_drawdown']:,.1f}"
        print(f"{r['strategy_name'][:45]:<45} | {r['total_trades']:<6} | {r['win_rate_pct']:<5.1f}% | {gross_str:<10} | {tax_str:<10} | {net_str:<10} | {dd_str:<8}")

    print("-" * 105)

    # Inspect the Best Strategy's Trade Log
    best_strategy = max(results, key=lambda x: x["net_pnl"])
    print(f"\nDetailed Trade Log for: {best_strategy['strategy_name']}")
    print(f"{'Entry Time':<19} | {'Type':<4} | {'Strike':<6} | {'Entry Prem':<10} | {'Exit Prem':<10} | {'Held':<6} | {'Net P&L':<10} | {'Outcome'}")
    print("-" * 105)

    sample_trades = best_strategy["trades"][-12:] if len(best_strategy["trades"]) >= 12 else best_strategy["trades"]
    for t in sample_trades:
        net_t = f"₹{t.net_pnl:+,.1f}"
        print(f"{t.entry_time:<19} | {t.option_type:<4} | {t.strike:<6} | ₹{t.entry_premium:<9.1f} | ₹{t.exit_premium:<9.1f} | {t.bars_held} min | {net_t:<10} | {t.exit_reason}")

    print("=" * 105)

if __name__ == "__main__":
    main()
