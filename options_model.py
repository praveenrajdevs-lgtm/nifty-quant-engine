"""
Black-Scholes Options Pricing Model (Pure Python, Zero External Dependencies)
Calculates exact Call & Put premiums, Delta, and Theta decay for Indian Index Options.
"""
import math

def norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def norm_pdf(x: float) -> float:
    """Probability density function for standard normal distribution."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

def calculate_option_price(spot: float, strike: float, time_to_expiry_years: float,
                           volatility: float = 0.15, risk_free_rate: float = 0.07,
                           option_type: str = "CE") -> dict:
    """
    Computes theoretical option price and greeks using Black-Scholes.
    
    :param spot: Current underlying index spot price (e.g., 24500)
    :param strike: Option strike price (e.g., 24500)
    :param time_to_expiry_years: Time to expiry in years (e.g., 2 days = 2 / 365)
    :param volatility: Implied Volatility (e.g., 0.15 for 15% IV, India VIX average)
    :param risk_free_rate: RBI repo rate baseline (~7% = 0.07)
    :param option_type: "CE" for Call Option, "PE" for Put Option
    :return: dict with price, delta, theta_per_day, intrinsic_value
    """
    # Guard against zero or negative time
    t = max(time_to_expiry_years, 0.0001)
    s = float(spot)
    k = float(strike)
    v = max(volatility, 0.01)
    r = risk_free_rate

    d1 = (math.log(s / k) + (r + 0.5 * v ** 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)

    if option_type.upper() == "CE":
        price = s * norm_cdf(d1) - k * math.exp(-r * t) * norm_cdf(d2)
        delta = norm_cdf(d1)
        theta = (- (s * norm_pdf(d1) * v) / (2 * math.sqrt(t))
                 - r * k * math.exp(-r * t) * norm_cdf(d2)) / 365.0
        intrinsic = max(0.0, s - k)
    else:  # PE
        price = k * math.exp(-r * t) * norm_cdf(-d2) - s * norm_cdf(-d1)
        delta = norm_cdf(d1) - 1.0
        theta = (- (s * norm_pdf(d1) * v) / (2 * math.sqrt(t))
                 + r * k * math.exp(-r * t) * norm_cdf(-d2)) / 365.0
        intrinsic = max(0.0, k - s)

    return {
        "price": round(max(price, intrinsic, 0.5), 2),
        "delta": round(delta, 3),
        "theta_per_day": round(theta, 2),
        "intrinsic": round(intrinsic, 2),
        "extrinsic": round(max(price - intrinsic, 0.0), 2)
    }

def get_atm_strike(spot: float, step: int = 50) -> int:
    """Finds nearest ATM strike (e.g. 50 step for Nifty, 100 for BankNifty)."""
    return int(round(spot / step) * step)
