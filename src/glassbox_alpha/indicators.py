from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from .models import Bar, MarketFeatures, Stance


def ema(values: list[float], period: int) -> float:
    if not values:
        raise ValueError("EMA requires at least one value")
    if period <= 0:
        raise ValueError("EMA period must be positive")
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        raise ValueError(f"RSI requires at least {period + 1} values")
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    window = changes[-period:]
    gains = sum(max(change, 0) for change in window) / period
    losses = sum(max(-change, 0) for change in window) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    relative_strength = gains / losses
    return 100 - (100 / (1 + relative_strength))


def realized_volatility(values: list[float], period: int = 20, periods_per_year: int = 252 * 78) -> float:
    if len(values) < period + 1:
        raise ValueError(f"Volatility requires at least {period + 1} values")
    returns = [math.log(values[index] / values[index - 1]) for index in range(1, len(values)) if values[index - 1] > 0]
    window = returns[-period:]
    return statistics.stdev(window) * math.sqrt(periods_per_year) if len(window) >= 2 else 0.0


def atr_percent(bars: list[Bar], period: int = 14) -> float:
    if len(bars) < period + 1:
        raise ValueError(f"ATR requires at least {period + 1} bars")
    true_ranges: list[float] = []
    for previous, current in zip(bars[-period - 1 : -1], bars[-period:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    spot = bars[-1].close
    return statistics.fmean(true_ranges) / spot if spot > 0 else 0.0


def _clip(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def build_features(
    symbol: str,
    bars: list[Bar],
    fast_period: int = 20,
    slow_period: int = 50,
    now: datetime | None = None,
) -> MarketFeatures:
    if len(bars) < slow_period + 1:
        raise ValueError(f"Need at least {slow_period + 1} bars, received {len(bars)}")
    ordered = sorted(bars, key=lambda item: item.timestamp)
    closes = [item.close for item in ordered]
    spot = closes[-1]
    fast = ema(closes, fast_period)
    slow = ema(closes, slow_period)
    rsi_value = rsi(closes)
    momentum = spot / closes[-6] - 1 if closes[-6] else 0.0
    vol = realized_volatility(closes)
    atr = atr_percent(ordered)

    trend_component = _clip((fast / slow - 1) / 0.015) if slow else 0.0
    momentum_component = _clip(momentum / 0.04)
    rsi_component = _clip((rsi_value - 50) / 25)
    # Trade in the direction of the medium trend after a short-term pullback.
    # The weights were selected on the first 70% of a 120-day SPY/QQQ sample;
    # the final 30% remained isolated for out-of-sample validation.
    score = _clip(0.50 * trend_component - 0.25 * momentum_component - 0.25 * rsi_component)
    baseline = Stance.BULLISH if score >= 0.18 else Stance.BEARISH if score <= -0.18 else Stance.NEUTRAL

    current = now or datetime.now(timezone.utc)
    bar_time = ordered[-1].timestamp
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    age = max(0.0, (current.astimezone(timezone.utc) - bar_time.astimezone(timezone.utc)).total_seconds())
    return MarketFeatures(
        symbol=symbol,
        timestamp=bar_time,
        spot=round(spot, 4),
        ema_fast=round(fast, 4),
        ema_slow=round(slow, 4),
        rsi_14=round(rsi_value, 2),
        momentum_5bar=round(momentum, 6),
        realized_vol_20bar=round(vol, 6),
        atr_pct_14bar=round(atr, 6),
        signal_score=round(score, 6),
        data_age_seconds=round(age, 2),
        baseline_stance=baseline,
    )
