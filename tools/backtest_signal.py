"""Walk-forward validation for the deterministic GlassBox signal.

This intentionally measures underlying directional returns, not option P&L.
Historical option spreads, fills, and implied volatility are not inferred.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from glassbox_alpha.indicators import build_features  # noqa: E402
from glassbox_alpha.models import Bar  # noqa: E402


@dataclass(frozen=True)
class Signal:
    symbol: str
    timestamp: datetime
    entry: float
    exit: float
    score: float
    direction: int
    model: str

    @property
    def gross_return(self) -> float:
        return self.direction * (self.exit / self.entry - 1)


@dataclass(frozen=True)
class Metrics:
    trades: int
    win_rate_pct: float
    average_return_pct: float
    cumulative_return_pct: float
    max_drawdown_pct: float
    profit_factor: float | None
    score: float


def fetch_bars(symbol: str, days: int) -> list[Bar]:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    key = os.environ["APCA_API_KEY_ID"]
    secret = os.environ["APCA_API_SECRET_KEY"]
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    response = StockHistoricalDataClient(key, secret).get_stock_bars(
        StockBarsRequest(
            symbol_or_symbols=symbol,
            start=end - timedelta(days=days),
            end=end,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            limit=10_000,
            feed=DataFeed.IEX,
            adjustment=Adjustment.ALL,
        )
    )
    eastern = ZoneInfo("America/New_York")
    result: list[Bar] = []
    for item in response[symbol]:
        local = item.timestamp.astimezone(eastern)
        minute = local.hour * 60 + local.minute
        if local.weekday() >= 5 or not 570 <= minute < 960:
            continue
        result.append(
            Bar(
                timestamp=item.timestamp.astimezone(timezone.utc),
                open=float(item.open), high=float(item.high), low=float(item.low),
                close=float(item.close), volume=float(item.volume),
            )
        )
    return sorted(result, key=lambda bar: bar.timestamp)


def model_score(features: object, model: str) -> float:
    trend = max(-1.0, min(1.0, (features.ema_fast / features.ema_slow - 1) / 0.015))
    momentum = max(-1.0, min(1.0, features.momentum_5bar / 0.04))
    rsi_component = max(-1.0, min(1.0, (features.rsi_14 - 50) / 25))
    weights = {
        "current_trend": (0.45, 0.35, 0.20),
        "slow_trend": (0.70, 0.20, 0.10),
        "trend_pullback": (0.50, -0.25, -0.25),
        "mean_reversion": (0.0, -0.55, -0.45),
    }[model]
    return max(-1.0, min(1.0, weights[0] * trend + weights[1] * momentum + weights[2] * rsi_component))


def candidate_signals(symbol: str, bars: list[Bar], threshold: float, hold_bars: int, model: str) -> list[Signal]:
    signals: list[Signal] = []
    next_allowed = 0
    for index in range(60, len(bars) - hold_bars - 1):
        if index < next_allowed:
            continue
        window = bars[max(0, index - 119): index + 1]
        features = build_features(symbol, window, now=window[-1].timestamp)
        score = model_score(features, model)
        if abs(score) < threshold:
            continue
        confidence = min(0.94, 0.56 + abs(score) * 0.42)
        if confidence < 0.64:
            continue
        entry_bar = bars[index + 1]
        exit_bar = bars[index + hold_bars]
        direction = 1 if score > 0 else -1
        signals.append(Signal(symbol, entry_bar.timestamp, entry_bar.open, exit_bar.close, score, direction, model))
        next_allowed = index + hold_bars + 1
    return signals


def portfolio(signals: list[Signal], split: datetime | None, *, test: bool) -> list[Signal]:
    filtered = [item for item in signals if split is None or (item.timestamp >= split) is test]
    filtered.sort(key=lambda item: (item.timestamp, -abs(item.score), item.symbol))
    accepted: list[Signal] = []
    daily: dict[str, int] = defaultdict(int)
    busy_until: datetime | None = None
    for signal in filtered:
        day = signal.timestamp.date().isoformat()
        if daily[day] >= 3 or (busy_until is not None and signal.timestamp < busy_until):
            continue
        accepted.append(signal)
        daily[day] += 1
        busy_until = signal.timestamp + timedelta(minutes=120)
    return accepted


def metrics(signals: list[Signal], round_trip_bps: float = 4.0) -> Metrics:
    returns = [item.gross_return - round_trip_bps / 10_000 for item in signals]
    if not returns:
        return Metrics(0, 0, 0, 0, 0, None, -999)
    equity = peak = 1.0
    maximum_drawdown = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, 1 - equity / peak)
    gains = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    deviation = statistics.stdev(returns) if len(returns) > 1 else 0.0
    selection_score = statistics.fmean(returns) / deviation * math.sqrt(len(returns)) if deviation else -999
    return Metrics(
        trades=len(returns),
        win_rate_pct=round(sum(value > 0 for value in returns) / len(returns) * 100, 2),
        average_return_pct=round(statistics.fmean(returns) * 100, 4),
        cumulative_return_pct=round((equity - 1) * 100, 3),
        max_drawdown_pct=round(maximum_drawdown * 100, 3),
        profit_factor=round(gains / losses, 3) if losses else None,
        score=round(selection_score, 4),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--symbols", default="SPY,QQQ")
    parser.add_argument("--hold-bars", type=int, default=24)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    bars_by_symbol = {symbol: fetch_bars(symbol, args.days) for symbol in symbols}
    timestamps = sorted({bar.timestamp for bars in bars_by_symbol.values() for bar in bars})
    split = timestamps[int(len(timestamps) * 0.70)]
    thresholds = [0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]
    models = ["current_trend", "slow_trend", "trend_pullback", "mean_reversion"]
    rows = []
    for model in models:
        for threshold in thresholds:
            candidates = [signal for symbol, bars in bars_by_symbol.items() for signal in candidate_signals(symbol, bars, threshold, args.hold_bars, model)]
            training = metrics(portfolio(candidates, split, test=False))
            testing = metrics(portfolio(candidates, split, test=True))
            rows.append({"model": model, "threshold": threshold, "training": asdict(training), "out_of_sample": asdict(testing)})
    eligible = [row for row in rows if row["training"]["trades"] >= 20]
    selected = max(eligible or rows, key=lambda row: row["training"]["score"])
    result = {
        "method": "underlying directional proxy; next-bar entry; 120-minute hold; 4 bps round trip; one position; max 3 entries/day",
        "not_modeled": "option premiums, IV, bid/ask spread, leg fills, DeepSeek vetoes, and hard option-chain gates",
        "source": "Alpaca IEX 5-minute adjusted regular-session bars",
        "symbols": symbols,
        "requested_calendar_days": args.days,
        "bars": {symbol: len(bars) for symbol, bars in bars_by_symbol.items()},
        "period": {"start": timestamps[0].isoformat(), "split": split.isoformat(), "end": timestamps[-1].isoformat()},
        "selection_rule": "highest training risk-adjusted score with at least 20 trades; out-of-sample data never selects the model or threshold",
        "selected_threshold": selected["threshold"],
        "selected_model": selected["model"],
        "results": rows,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
