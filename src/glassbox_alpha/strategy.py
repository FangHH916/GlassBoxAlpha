from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

from .config import Settings
from .models import (
    AccountState,
    LegAction,
    MarketFeatures,
    OptionContractQuote,
    OptionLeg,
    OptionType,
    ResearchThesis,
    Stance,
    TradeProposal,
)


def deterministic_thesis(features: MarketFeatures) -> ResearchThesis:
    confidence = min(0.94, 0.56 + abs(features.signal_score) * 0.42)
    direction = features.baseline_stance
    trend_pct = (features.ema_fast / features.ema_slow - 1) * 100 if features.ema_slow else 0.0
    catalysts = [
        f"Fast/slow EMA spread is {trend_pct:+.2f}%",
        f"Five-period momentum is {features.momentum_5d * 100:+.2f}%",
        f"RSI(14) is {features.rsi_14:.1f}",
    ]
    risks = [
        f"Annualized realized volatility estimate is {features.realized_vol_20 * 100:.1f}%",
        "Short competition window makes P&L statistically noisy",
        "Indicative options data may differ from the paper matching NBBO",
    ]
    return ResearchThesis(
        stance=direction,
        confidence=round(confidence, 3),
        horizon_days=3,
        summary=(
            f"Completed-bar evidence is {direction.value} with normalized signal "
            f"{features.signal_score:+.2f}."
        ),
        catalysts=catalysts,
        risks=risks,
        invalidation="Signal score enters the neutral zone or changes sign.",
        source="deterministic_candidate_factory",
    )


class StrategyPlanner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def plan(
        self,
        features: MarketFeatures,
        thesis: ResearchThesis,
        chain: list[OptionContractQuote],
        account: AccountState,
        now: datetime | None = None,
    ) -> TradeProposal | None:
        if thesis.stance is Stance.NEUTRAL:
            return None
        option_type = OptionType.CALL if thesis.stance is Stance.BULLISH else OptionType.PUT
        candidates = [
            item
            for item in chain
            if item.underlying == features.symbol
            and item.option_type is option_type
            and self.settings.min_dte <= item.dte <= self.settings.max_dte
            and item.tradable
            and item.ask > 0
            and 0 <= item.bid <= item.ask
        ]
        if not candidates:
            return None

        liquid = [
            item
            for item in candidates
            if item.open_interest >= self.settings.min_open_interest
            and item.spread_pct <= self.settings.max_quote_spread_pct
        ]
        pool = liquid or candidates
        expiration = min(
            {item.expiration for item in pool},
            key=lambda item: abs((item - (now or datetime.now(timezone.utc)).date()).days - 12),
        )
        expiry_pool = [item for item in pool if item.expiration == expiration]
        long_leg = min(expiry_pool, key=lambda item: self._delta_distance(item, self.settings.target_long_delta, features.spot))

        if account.options_trading_level >= 3:
            risk_budget = account.equity * self.settings.risk_per_trade_pct
            short_pool = [
                item
                for item in expiry_pool
                if item.symbol != long_leg.symbol
                and (
                    item.strike > long_leg.strike
                    if option_type is OptionType.CALL
                    else item.strike < long_leg.strike
                )
                and abs(item.strike - long_leg.strike) <= 5
                and 0 < round(long_leg.midpoint - item.midpoint, 2) * 100 <= risk_budget
            ]
            if short_pool:
                short_leg = min(
                    short_pool,
                    key=lambda item: self._delta_distance(item, self.settings.target_short_delta, features.spot),
                )
                spread = self._spread(features, thesis, account, long_leg, short_leg, now)
                if spread is not None:
                    return spread
        return self._single(features, thesis, account, long_leg, now)

    @staticmethod
    def _delta_distance(contract: OptionContractQuote, target: float, spot: float) -> float:
        if contract.delta is not None:
            return abs(abs(contract.delta) - target)
        moneyness_target = 1.0 if target >= 0.4 else 1.01
        if contract.option_type is OptionType.PUT:
            moneyness_target = 2.0 - moneyness_target
        return abs(contract.strike / spot - moneyness_target) + 0.5

    def _spread(
        self,
        features: MarketFeatures,
        thesis: ResearchThesis,
        account: AccountState,
        long_leg: OptionContractQuote,
        short_leg: OptionContractQuote,
        now: datetime | None,
    ) -> TradeProposal | None:
        width = abs(short_leg.strike - long_leg.strike)
        limit_debit = round(max(0.01, long_leg.midpoint - short_leg.midpoint), 2)
        if width <= 0 or limit_debit >= width:
            return None
        risk_per_contract = limit_debit * 100
        quantity = self._quantity(account, risk_per_contract)
        max_loss = round(risk_per_contract * quantity, 2)
        max_profit = round((width - limit_debit) * 100 * quantity, 2)
        legs = [
            OptionLeg(long_leg, LegAction.BUY_TO_OPEN),
            OptionLeg(short_leg, LegAction.SELL_TO_OPEN),
        ]
        created = now or datetime.now(timezone.utc)
        proposal_id = self._proposal_id(features, legs, quantity, limit_debit)
        return TradeProposal(
            proposal_id=proposal_id,
            created_at=created,
            underlying=features.symbol,
            direction=thesis.stance,
            structure="bull_call_debit_spread" if thesis.stance is Stance.BULLISH else "bear_put_debit_spread",
            legs=legs,
            quantity=quantity,
            limit_debit=limit_debit,
            max_loss=max_loss,
            max_profit=max_profit,
            thesis=thesis,
            rationale=f"Defined-risk vertical selected near |delta| {self.settings.target_long_delta:.2f}/{self.settings.target_short_delta:.2f}.",
        )

    def _single(
        self,
        features: MarketFeatures,
        thesis: ResearchThesis,
        account: AccountState,
        contract: OptionContractQuote,
        now: datetime | None,
    ) -> TradeProposal:
        limit_debit = round(max(0.01, contract.midpoint), 2)
        risk_per_contract = limit_debit * 100
        # Level-2 fallback deliberately uses half of the normal risk budget.
        quantity = self._quantity(account, risk_per_contract, budget_multiplier=0.5)
        legs = [OptionLeg(contract, LegAction.BUY_TO_OPEN)]
        created = now or datetime.now(timezone.utc)
        proposal_id = self._proposal_id(features, legs, quantity, limit_debit)
        return TradeProposal(
            proposal_id=proposal_id,
            created_at=created,
            underlying=features.symbol,
            direction=thesis.stance,
            structure="long_call" if thesis.stance is Stance.BULLISH else "long_put",
            legs=legs,
            quantity=quantity,
            limit_debit=limit_debit,
            max_loss=round(risk_per_contract * quantity, 2),
            max_profit=None,
            thesis=thesis,
            rationale="Options level below 3: limited-risk single-leg fallback at half risk budget.",
        )

    def _quantity(self, account: AccountState, risk_per_contract: float, budget_multiplier: float = 1.0) -> int:
        budget = account.equity * self.settings.risk_per_trade_pct * budget_multiplier
        if risk_per_contract <= 0:
            return 1
        return max(1, min(self.settings.max_contracts_per_trade, math.floor(budget / risk_per_contract)))

    @staticmethod
    def _proposal_id(
        features: MarketFeatures,
        legs: list[OptionLeg],
        quantity: int,
        limit_debit: float,
    ) -> str:
        canonical = {
            "symbol": features.symbol,
            "feature_timestamp": features.timestamp.isoformat(),
            "legs": [(leg.contract.symbol, leg.action.value, leg.ratio) for leg in legs],
            "quantity": quantity,
            "limit_debit": limit_debit,
        }
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()
        return f"gba-{digest[:24]}"
