from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "on"}


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in TRUE_VALUES


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    project_root: Path
    mode: str = "demo"
    execution_mode: str = "preview"
    underlyings: tuple[str, ...] = ("SPY", "QQQ")
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    deepseek_api_key: str | None = None
    ai_model: str = "deepseek-v4-flash"
    use_deepseek: bool = False
    option_feed: str = "indicative"
    fast_ema: int = 20
    slow_ema: int = 50
    min_confidence: float = 0.64
    min_dte: int = 7
    max_dte: int = 21
    target_long_delta: float = 0.55
    target_short_delta: float = 0.30
    min_signal_score: float = 0.45
    min_open_interest: int = 500
    max_quote_spread_pct: float = 0.12
    max_quote_age_seconds: int = 30
    risk_per_trade_pct: float = 0.005
    max_option_exposure_pct: float = 0.01
    max_daily_loss_pct: float = 0.0125
    max_drawdown_pct: float = 0.03
    max_trades_per_day: int = 3
    max_positions: int = 1
    max_contracts_per_trade: int = 3
    max_data_age_seconds: int = 900
    min_minutes_to_close: int = 45
    competition_starting_balance: float = 100_000.0
    allow_paper_orders: bool = False
    paper_confirmation: str | None = None
    alpaca_execution_backend: str = "cli"
    alpaca_cli_path: str = "alpaca"
    competition_account_id: str | None = None
    competition_start_utc: str = "2026-08-28T15:00:00+00:00"
    db_path: Path = field(default_factory=lambda: Path("data/glassbox_alpha.sqlite3"))
    kill_switch_path: Path = field(default_factory=lambda: Path("data/KILL_SWITCH"))

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        db_raw = Path(os.getenv("DATABASE_PATH", "data/glassbox_alpha.sqlite3"))
        kill_raw = Path(os.getenv("KILL_SWITCH_PATH", "data/KILL_SWITCH"))
        settings = cls(
            project_root=root,
            mode=os.getenv("BROKER_MODE", "demo").strip().lower(),
            execution_mode=os.getenv("EXECUTION_MODE", "preview").strip().lower(),
            underlyings=_csv("UNDERLYINGS", "SPY,QQQ"),
            alpaca_api_key=os.getenv("APCA_API_KEY_ID"),
            alpaca_api_secret=os.getenv("APCA_API_SECRET_KEY"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            ai_model=os.getenv("AI_MODEL", "deepseek-v4-flash"),
            use_deepseek=_bool("USE_DEEPSEEK", False),
            option_feed=os.getenv("OPTION_FEED", "indicative").strip().lower(),
            fast_ema=_int("FAST_EMA", 20),
            slow_ema=_int("SLOW_EMA", 50),
            min_confidence=_float("MIN_CONFIDENCE", 0.64),
            min_dte=_int("MIN_DTE", 7),
            max_dte=_int("MAX_DTE", 21),
            target_long_delta=_float("TARGET_LONG_DELTA", 0.55),
            target_short_delta=_float("TARGET_SHORT_DELTA", 0.30),
            min_signal_score=_float("MIN_SIGNAL_SCORE", 0.45),
            min_open_interest=_int("MIN_OPEN_INTEREST", 500),
            max_quote_spread_pct=_float("MAX_QUOTE_SPREAD_PCT", 0.12),
            max_quote_age_seconds=_int("MAX_QUOTE_AGE_SECONDS", 30),
            risk_per_trade_pct=_float("RISK_PER_TRADE_PCT", 0.005),
            max_option_exposure_pct=_float("MAX_OPTION_EXPOSURE_PCT", 0.01),
            max_daily_loss_pct=_float("MAX_DAILY_LOSS_PCT", 0.0125),
            max_drawdown_pct=_float("MAX_DRAWDOWN_PCT", 0.03),
            max_trades_per_day=_int("MAX_TRADES_PER_DAY", 3),
            max_positions=_int("MAX_OPTION_POSITIONS", 1),
            max_contracts_per_trade=_int("MAX_CONTRACTS_PER_TRADE", 3),
            max_data_age_seconds=_int("MAX_DATA_AGE_SECONDS", 900),
            min_minutes_to_close=_int("MIN_MINUTES_TO_CLOSE", 45),
            competition_starting_balance=_float("COMPETITION_STARTING_BALANCE", 100_000.0),
            allow_paper_orders=_bool("ALLOW_PAPER_ORDERS", False),
            paper_confirmation=os.getenv("PAPER_ORDER_CONFIRMATION"),
            alpaca_execution_backend=os.getenv("ALPACA_EXECUTION_BACKEND", "cli").strip().lower(),
            alpaca_cli_path=os.getenv("ALPACA_CLI_PATH", "alpaca").strip(),
            competition_account_id=os.getenv("COMPETITION_ACCOUNT_ID"),
            competition_start_utc=os.getenv("COMPETITION_START_UTC", "2026-08-28T15:00:00+00:00"),
            db_path=db_raw if db_raw.is_absolute() else root / db_raw,
            kill_switch_path=kill_raw if kill_raw.is_absolute() else root / kill_raw,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in {"demo", "alpaca"}:
            raise ValueError("BROKER_MODE must be 'demo' or 'alpaca'")
        if self.execution_mode not in {"preview", "paper"}:
            raise ValueError("EXECUTION_MODE must be 'preview' or 'paper'; live trading is intentionally unsupported")
        if self.mode == "alpaca" and (not self.alpaca_api_key or not self.alpaca_api_secret):
            raise ValueError("Alpaca mode requires APCA_API_KEY_ID and APCA_API_SECRET_KEY")
        if self.use_deepseek and not self.deepseek_api_key:
            raise ValueError("USE_DEEPSEEK=true requires DEEPSEEK_API_KEY")
        if self.fast_ema >= self.slow_ema:
            raise ValueError("FAST_EMA must be smaller than SLOW_EMA")
        if self.fast_ema < 2 or self.slow_ema < 3:
            raise ValueError("EMA periods are too short")
        if not self.underlyings or any(not item.isalpha() for item in self.underlyings):
            raise ValueError("UNDERLYINGS must contain alphabetic symbols")
        if not 0 < self.risk_per_trade_pct <= self.max_option_exposure_pct <= 0.25:
            raise ValueError("Risk percentages are invalid or unsafe")
        if not 0.5 <= self.min_confidence <= 1:
            raise ValueError("MIN_CONFIDENCE must be between 0.5 and 1")
        if self.min_dte < 1 or self.max_dte < self.min_dte:
            raise ValueError("DTE range is invalid")
        if not 0 < self.min_signal_score <= 1:
            raise ValueError("MIN_SIGNAL_SCORE must be between 0 and 1")
        if not 0 < self.max_quote_spread_pct <= 0.5:
            raise ValueError("MAX_QUOTE_SPREAD_PCT must be between 0 and 0.5")
        if self.max_quote_age_seconds <= 0 or self.max_data_age_seconds <= 0:
            raise ValueError("Data freshness limits must be positive")
        if min(self.max_trades_per_day, self.max_positions, self.max_contracts_per_trade) < 1:
            raise ValueError("Trade, position, and contract limits must be positive")
        competition_start = datetime.fromisoformat(self.competition_start_utc.replace("Z", "+00:00"))
        if competition_start.tzinfo is None:
            raise ValueError("COMPETITION_START_UTC must include a timezone")
        if self.alpaca_execution_backend not in {"cli", "sdk"}:
            raise ValueError("ALPACA_EXECUTION_BACKEND must be 'cli' or 'sdk'")

    @property
    def paper_execution_unlocked(self) -> bool:
        return (
            self.mode == "alpaca"
            and self.execution_mode == "paper"
            and self.allow_paper_orders
            and self.paper_confirmation == "I_UNDERSTAND_PAPER_ONLY"
            and bool(self.competition_account_id)
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "execution_mode": self.execution_mode,
            "underlyings": list(self.underlyings),
            "ai_provider": "DeepSeek" if self.use_deepseek else "deterministic fallback",
            "ai_model": self.ai_model if self.use_deepseek else None,
            "option_feed": self.option_feed,
            "paper_execution_unlocked": self.paper_execution_unlocked,
            "alpaca_execution_backend": self.alpaca_execution_backend,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_option_exposure_pct": self.max_option_exposure_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_trades_per_day": self.max_trades_per_day,
        }
