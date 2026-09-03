from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


class Stance(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class LegAction(str, Enum):
    BUY_TO_OPEN = "buy_to_open"
    SELL_TO_OPEN = "sell_to_open"
    BUY_TO_CLOSE = "buy_to_close"
    SELL_TO_CLOSE = "sell_to_close"


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class MarketFeatures:
    symbol: str
    timestamp: datetime
    spot: float
    ema_fast: float
    ema_slow: float
    rsi_14: float
    momentum_5bar: float
    realized_vol_20bar: float
    atr_pct_14bar: float
    signal_score: float
    data_age_seconds: float
    baseline_stance: Stance


@dataclass(frozen=True)
class ResearchThesis:
    stance: Stance
    confidence: float
    horizon_days: int
    summary: str
    catalysts: list[str]
    risks: list[str]
    invalidation: str
    source: str
    model: str | None = None


@dataclass(frozen=True)
class CriticVerdict:
    candidate_id: str
    verdict: str
    risk_flags: list[str]
    evidence_ids: list[str]
    thesis: str
    invalidated_if: str
    source: str
    model: str | None = None


@dataclass(frozen=True)
class OptionContractQuote:
    symbol: str
    underlying: str
    option_type: OptionType
    strike: float
    expiration: date
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    delta: float | None
    gamma: float | None
    theta: float | None
    implied_volatility: float | None
    open_interest: int
    tradable: bool
    quote_timestamp: datetime
    feed: str = "indicative"

    @property
    def midpoint(self) -> float:
        if self.bid <= 0:
            return self.ask
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_pct(self) -> float:
        mid = self.midpoint
        return (self.ask - self.bid) / mid if mid > 0 else float("inf")

    @property
    def dte(self) -> int:
        return (self.expiration - self.quote_timestamp.date()).days


@dataclass(frozen=True)
class OptionLeg:
    contract: OptionContractQuote
    action: LegAction
    ratio: int = 1


@dataclass(frozen=True)
class TradeProposal:
    proposal_id: str
    created_at: datetime
    underlying: str
    direction: Stance
    structure: str
    legs: list[OptionLeg]
    quantity: int
    limit_debit: float
    max_loss: float
    max_profit: float | None
    thesis: ResearchThesis
    rationale: str


@dataclass(frozen=True)
class AccountState:
    equity: float
    last_equity: float
    buying_power: float
    options_buying_power: float
    option_market_value: float
    daily_pnl: float
    high_watermark: float
    open_option_positions: int
    trades_today: int
    options_trading_level: int
    is_paper: bool
    market_open: bool
    minutes_to_close: int | None = None
    account_id_masked: str | None = None
    account_created_at: datetime | None = None
    competition_account_match: bool = True
    competition_account_fresh: bool = True
    competition_balance_verified: bool = True
    pending_orders: int = 0

    @property
    def drawdown_pct(self) -> float:
        if self.high_watermark <= 0:
            return 0.0
        return max(0.0, (self.high_watermark - self.equity) / self.high_watermark)


@dataclass(frozen=True)
class RiskCheck:
    code: str
    label: str
    passed: bool
    detail: str
    observed: float | str | bool | None = None
    limit: float | str | bool | None = None


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    checks: list[RiskCheck]
    approved_quantity: int
    total_risk: float
    summary: str


@dataclass(frozen=True)
class OrderReceipt:
    order_id: str
    client_order_id: str
    status: str
    submitted_at: datetime
    paper: bool


@dataclass(frozen=True)
class CycleReport:
    run_id: str
    created_at: datetime
    completed_at: datetime
    status: str
    mode: str
    execution_mode: str
    symbol: str
    features: MarketFeatures | None
    thesis: ResearchThesis | None
    proposal: TradeProposal | None
    critic: CriticVerdict | None
    risk: RiskDecision | None
    orders: list[OrderReceipt] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def to_primitive(value: Any) -> Any:
    """Convert nested dataclasses/enums/dates into JSON-safe primitives."""
    if is_dataclass(value):
        return {key: to_primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    return value


def proposal_from_primitive(value: dict[str, Any]) -> TradeProposal:
    thesis_raw = value["thesis"]
    thesis = ResearchThesis(
        stance=Stance(thesis_raw["stance"]),
        confidence=float(thesis_raw["confidence"]),
        horizon_days=int(thesis_raw["horizon_days"]),
        summary=str(thesis_raw["summary"]),
        catalysts=list(thesis_raw["catalysts"]),
        risks=list(thesis_raw["risks"]),
        invalidation=str(thesis_raw["invalidation"]),
        source=str(thesis_raw["source"]),
        model=thesis_raw.get("model"),
    )
    legs: list[OptionLeg] = []
    for leg_raw in value["legs"]:
        contract_raw = leg_raw["contract"]
        contract = OptionContractQuote(
            symbol=str(contract_raw["symbol"]),
            underlying=str(contract_raw["underlying"]),
            option_type=OptionType(contract_raw["option_type"]),
            strike=float(contract_raw["strike"]),
            expiration=date.fromisoformat(contract_raw["expiration"]),
            bid=float(contract_raw["bid"]),
            ask=float(contract_raw["ask"]),
            bid_size=int(contract_raw["bid_size"]),
            ask_size=int(contract_raw["ask_size"]),
            delta=float(contract_raw["delta"]) if contract_raw.get("delta") is not None else None,
            gamma=float(contract_raw["gamma"]) if contract_raw.get("gamma") is not None else None,
            theta=float(contract_raw["theta"]) if contract_raw.get("theta") is not None else None,
            implied_volatility=(
                float(contract_raw["implied_volatility"])
                if contract_raw.get("implied_volatility") is not None
                else None
            ),
            open_interest=int(contract_raw["open_interest"]),
            tradable=bool(contract_raw["tradable"]),
            quote_timestamp=datetime.fromisoformat(contract_raw["quote_timestamp"]),
            feed=str(contract_raw.get("feed", "unknown")),
        )
        legs.append(OptionLeg(contract, LegAction(leg_raw["action"]), int(leg_raw.get("ratio", 1))))
    return TradeProposal(
        proposal_id=str(value["proposal_id"]),
        created_at=datetime.fromisoformat(value["created_at"]),
        underlying=str(value["underlying"]),
        direction=Stance(value["direction"]),
        structure=str(value["structure"]),
        legs=legs,
        quantity=int(value["quantity"]),
        limit_debit=float(value["limit_debit"]),
        max_loss=float(value["max_loss"]),
        max_profit=float(value["max_profit"]) if value.get("max_profit") is not None else None,
        thesis=thesis,
        rationale=str(value["rationale"]),
    )
