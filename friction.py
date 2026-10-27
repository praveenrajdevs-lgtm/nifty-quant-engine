"""
Indian Stock Market Transaction Costs Calculator (Zerodha / SEBI Regulations)
Calculates exact real-world friction: Brokerage, STT, Exchange fee, GST, Stamp Duty.
"""

def calculate_option_trade_costs(buy_price: float, sell_price: float, quantity: int) -> dict:
    """
    Calculates exact charges for 1 complete round-trip option trade (Buy + Sell).
    
    :param buy_price: Option premium bought at (e.g. 150.0)
    :param sell_price: Option premium sold at (e.g. 162.0)
    :param quantity: Number of contracts (e.g. 25 for 1 lot Nifty)
    :return: dict with detailed breakdown and total charges
    """
    buy_turnover = buy_price * quantity
    sell_turnover = sell_price * quantity
    total_turnover = buy_turnover + sell_turnover

    # 1. Brokerage (Zerodha: ₹20 per executed order, max ₹40 round trip)
    brokerage = 20.0 + 20.0

    # 2. STT (Securities Transaction Tax - 0.1% on Sell Turnover for options)
    stt = round(sell_turnover * 0.001, 2)

    # 3. Exchange Turnover Charges (NSE: ~0.035% on total premium turnover)
    exchange_charges = round(total_turnover * 0.00035, 2)

    # 4. GST: 18% on (Brokerage + Exchange Charges)
    gst = round((brokerage + exchange_charges) * 0.18, 2)

    # 5. SEBI Turnover Charges (₹10 per Crore = 0.0001%)
    sebi_charges = round(total_turnover * 0.000001, 2)

    # 6. Stamp Duty (0.003% on Buy side only)
    stamp_duty = round(buy_turnover * 0.00003, 2)

    total_charges = round(brokerage + stt + exchange_charges + gst + sebi_charges + stamp_duty, 2)

    gross_pnl = round(sell_turnover - buy_turnover, 2)
    net_pnl = round(gross_pnl - total_charges, 2)

    return {
        "gross_pnl": gross_pnl,
        "total_charges": total_charges,
        "net_pnl": net_pnl,
        "breakdown": {
            "brokerage": brokerage,
            "stt": stt,
            "exchange_charges": exchange_charges,
            "gst": gst,
            "sebi_charges": sebi_charges,
            "stamp_duty": stamp_duty
        }
    }
