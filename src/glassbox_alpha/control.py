from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

from .audit import AuditStore
from .config import Settings


STRATEGIES = ("auto", "trend_pullback", "volatility_expansion", "momentum_breakout", "mean_reversion")
CONTROL_KEY = "owner_strategy_control_v1"


@dataclass(frozen=True)
class RuntimeControl:
    enabled: bool
    strategy: str
    underlyings: tuple[str, ...]
    min_signal_score: float
    risk_per_trade_pct: float
    max_option_exposure_pct: float
    max_trades_per_day: int
    max_positions: int
    max_hold_minutes: int
    profit_target_pct: float
    stop_loss_pct: float
    scan_interval_seconds: int
    version: int = 1
    updated_at: str = ""

    @classmethod
    def defaults(cls, settings: Settings) -> "RuntimeControl":
        return cls(
            enabled=True,
            strategy="trend_pullback",
            underlyings=settings.underlyings,
            min_signal_score=settings.min_signal_score,
            risk_per_trade_pct=settings.risk_per_trade_pct,
            max_option_exposure_pct=settings.max_option_exposure_pct,
            max_trades_per_day=settings.max_trades_per_day,
            max_positions=settings.max_positions,
            max_hold_minutes=settings.max_hold_minutes,
            profit_target_pct=settings.profit_target_pct,
            stop_loss_pct=settings.stop_loss_pct,
            scan_interval_seconds=300,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def public_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["underlyings"] = list(self.underlyings)
        value["paper_only"] = True
        value["hard_limits"] = {
            "min_signal_score": [0.20, 0.60],
            "risk_per_trade_pct": [0.0005, 0.0025],
            "max_option_exposure_pct": [0.0025, 0.01],
            "max_trades_per_day": [1, 8],
            "max_positions": [1, 3],
            "max_hold_minutes": [30, 120],
            "profit_target_pct": [0.10, 0.50],
            "stop_loss_pct": [0.10, 0.25],
            "scan_interval_seconds": [300, 3600],
        }
        return value


def load_control(store: AuditStore, settings: Settings) -> RuntimeControl:
    raw = store.get_runtime(CONTROL_KEY)
    if not raw:
        return RuntimeControl.defaults(settings)
    try:
        return validate_control(json.loads(raw), settings, current=None)
    except (TypeError, ValueError, json.JSONDecodeError):
        return RuntimeControl.defaults(settings)


def save_control(store: AuditStore, control: RuntimeControl) -> None:
    store.set_runtime(CONTROL_KEY, json.dumps(control.public_dict(), separators=(",", ":")))


def validate_control(payload: dict[str, object], settings: Settings, current: RuntimeControl | None) -> RuntimeControl:
    base = current or RuntimeControl.defaults(settings)
    allowed = set(RuntimeControl.__dataclass_fields__)
    unknown = set(payload) - allowed - {"paper_only", "hard_limits"}
    if unknown:
        raise ValueError(f"Unsupported control fields: {', '.join(sorted(unknown))}")

    def number(name: str, low: float, high: float) -> float:
        value = float(payload.get(name, getattr(base, name)))
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return value

    def integer(name: str, low: int, high: int) -> int:
        raw = payload.get(name, getattr(base, name))
        if isinstance(raw, bool) or int(raw) != float(raw):
            raise ValueError(f"{name} must be an integer")
        value = int(raw)
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return value

    enabled = payload.get("enabled", base.enabled)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    strategy = str(payload.get("strategy", base.strategy)).strip().lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of: {', '.join(STRATEGIES)}")
    raw_symbols = payload.get("underlyings", list(base.underlyings))
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise ValueError("underlyings must be a non-empty list")
    symbols = tuple(dict.fromkeys(str(item).strip().upper() for item in raw_symbols))
    if any(item not in settings.underlyings for item in symbols):
        raise ValueError(f"underlyings must be selected from: {', '.join(settings.underlyings)}")

    exposure = number("max_option_exposure_pct", 0.0025, 0.01)
    risk = number("risk_per_trade_pct", 0.0005, 0.0025)
    if risk > exposure:
        raise ValueError("risk_per_trade_pct cannot exceed max_option_exposure_pct")
    return RuntimeControl(
        enabled=enabled,
        strategy=strategy,
        underlyings=symbols,
        min_signal_score=number("min_signal_score", 0.20, 0.60),
        risk_per_trade_pct=risk,
        max_option_exposure_pct=exposure,
        max_trades_per_day=integer("max_trades_per_day", 1, 8),
        max_positions=integer("max_positions", 1, 3),
        max_hold_minutes=integer("max_hold_minutes", 30, 120),
        profit_target_pct=number("profit_target_pct", 0.10, 0.50),
        stop_loss_pct=number("stop_loss_pct", 0.10, 0.25),
        scan_interval_seconds=integer("scan_interval_seconds", 300, 3600),
        version=(base.version + 1) if current else int(payload.get("version", base.version)),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def effective_settings(base: Settings, control: RuntimeControl) -> Settings:
    return replace(
        base,
        underlyings=control.underlyings,
        min_signal_score=control.min_signal_score,
        risk_per_trade_pct=control.risk_per_trade_pct,
        max_option_exposure_pct=control.max_option_exposure_pct,
        max_trades_per_day=control.max_trades_per_day,
        max_positions=control.max_positions,
        max_hold_minutes=control.max_hold_minutes,
        profit_target_pct=control.profit_target_pct,
        stop_loss_pct=control.stop_loss_pct,
    )
