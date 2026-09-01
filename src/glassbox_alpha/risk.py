from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings
from .models import (
    AccountState,
    CriticVerdict,
    LegAction,
    MarketFeatures,
    OptionType,
    RiskCheck,
    RiskDecision,
    Stance,
    TradeProposal,
)


class RiskKernel:
    """Non-AI, fail-closed gatekeeper. Every submitted order must pass all checks."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(
        self,
        proposal: TradeProposal,
        features: MarketFeatures,
        critic: CriticVerdict,
        account: AccountState,
        *,
        duplicate: bool,
        kill_switch: bool,
        now: datetime | None = None,
    ) -> RiskDecision:
        current = now or datetime.now(timezone.utc)
        checks: list[RiskCheck] = []

        def add(code: str, label: str, passed: bool, detail: str, observed=None, limit=None) -> None:
            checks.append(RiskCheck(code, label, bool(passed), detail, observed, limit))

        add("paper_only", "Paper environment", account.is_paper, "Live trading is not implemented.", account.is_paper, True)
        execution_ready = self.settings.execution_mode == "preview" or self.settings.paper_execution_unlocked
        add("execution_lock", "Execution interlock", execution_ready, "Paper orders require mode, opt-in, exact confirmation, and configured account ID.", execution_ready, True)
        add("competition_account", "Dedicated competition account", account.competition_account_match, "Configured account ID must match the authenticated paper account.", account.competition_account_match, True)
        add("fresh_account", "Fresh competition account", account.competition_account_fresh, "Competition execution requires an account created for this event.", account.competition_account_fresh, True)
        add("starting_balance", "$100k starting baseline", account.competition_balance_verified, "Baseline is verified once before competition trading begins and persisted locally.", account.competition_balance_verified, True)
        add("kill_switch", "Kill switch", not kill_switch, "New orders stop immediately when engaged.", kill_switch, False)
        add("market_open", "Market open", account.market_open, "Options orders require the regular session.", account.market_open, True)
        minutes_ok = account.minutes_to_close is None or account.minutes_to_close >= self.settings.min_minutes_to_close
        add("close_buffer", "Closing-time buffer", minutes_ok, "Avoid opening positions near the closing bell.", account.minutes_to_close, self.settings.min_minutes_to_close)
        add("unique_candidate", "Idempotency", not duplicate, "A candidate may be submitted only once.", duplicate, False)
        add("critic_verdict", "AI critic", critic.verdict == "ALLOW", "AI has veto-only authority.", critic.verdict, "ALLOW")
        add("critic_identity", "Immutable candidate", critic.candidate_id == proposal.proposal_id, "Critic cannot modify the candidate.", critic.candidate_id, proposal.proposal_id)
        symbol_ok = bool(proposal.legs) and proposal.underlying == features.symbol and all(
            leg.contract.underlying == features.symbol for leg in proposal.legs
        )
        add("candidate_symbol", "Candidate symbol", symbol_ok, "The proposal and every leg must match the feature symbol.", proposal.underlying, features.symbol)
        aligned = proposal.direction is features.baseline_stance and proposal.direction is not Stance.NEUTRAL
        add("regime_alignment", "Signal alignment", aligned, "Candidate direction must equal the deterministic regime.", proposal.direction.value, features.baseline_stance.value)
        expected_option_type = OptionType.CALL if proposal.direction is Stance.BULLISH else OptionType.PUT
        direction_ok = (
            proposal.direction is not Stance.NEUTRAL
            and proposal.thesis.stance is proposal.direction
            and bool(proposal.legs)
            and all(leg.contract.option_type is expected_option_type for leg in proposal.legs)
        )
        add("direction_contract", "Directional contract", direction_ok, "Bullish candidates use calls and bearish candidates use puts.", expected_option_type.value, expected_option_type.value)
        signal_ok = abs(features.signal_score) >= self.settings.min_signal_score
        add("signal_strength", "Signal strength", signal_ok, "Weak evidence produces abstention.", round(abs(features.signal_score), 3), self.settings.min_signal_score)
        confidence_ok = proposal.thesis.confidence >= self.settings.min_confidence
        add("confidence", "Candidate confidence", confidence_ok, "Minimum deterministic confidence.", proposal.thesis.confidence, self.settings.min_confidence)
        data_fresh = features.data_age_seconds <= self.settings.max_data_age_seconds
        add("bar_freshness", "Bar freshness", data_fresh, "Stale features cannot open risk.", features.data_age_seconds, self.settings.max_data_age_seconds)

        required_level = 3 if len(proposal.legs) > 1 else 2
        add("option_level", "Options permission", account.options_trading_level >= required_level, "Account permission must support the structure.", account.options_trading_level, required_level)
        add("position_limit", "Position limit", account.open_option_positions < self.settings.max_positions, "Cap simultaneous option positions.", account.open_option_positions, self.settings.max_positions)
        add("trade_limit", "Daily trade limit", account.trades_today < self.settings.max_trades_per_day, "Cap new entries per session.", account.trades_today, self.settings.max_trades_per_day)

        daily_floor = -account.equity * self.settings.max_daily_loss_pct
        add("daily_loss", "Daily loss circuit", account.daily_pnl > daily_floor, "Stop opening risk after the daily loss budget is consumed.", round(account.daily_pnl, 2), round(daily_floor, 2))
        add("drawdown", "Peak drawdown circuit", account.drawdown_pct < self.settings.max_drawdown_pct, "Peak-to-current equity circuit breaker.", round(account.drawdown_pct, 4), self.settings.max_drawdown_pct)
        per_trade_limit = account.equity * self.settings.risk_per_trade_pct
        add("max_loss", "Maximum loss", proposal.max_loss <= per_trade_limit, "Defined max loss must fit the per-trade budget.", proposal.max_loss, round(per_trade_limit, 2))
        total_after = account.option_market_value + proposal.max_loss
        exposure_limit = account.equity * self.settings.max_option_exposure_pct
        add("portfolio_risk", "Portfolio risk", total_after <= exposure_limit, "Existing option exposure plus max loss stays capped.", round(total_after, 2), round(exposure_limit, 2))
        add("contract_count", "Contract count", 1 <= proposal.quantity <= self.settings.max_contracts_per_trade, "Contracts must be a small positive integer.", proposal.quantity, self.settings.max_contracts_per_trade)

        expected_loss = round(proposal.limit_debit * 100 * proposal.quantity, 2)
        if len(proposal.legs) == 2:
            width = abs(proposal.legs[0].contract.strike - proposal.legs[1].contract.strike)
            expected_profit = round((width - proposal.limit_debit) * 100 * proposal.quantity, 2)
            economics_ok = abs(proposal.max_loss - expected_loss) <= 0.01 and (
                proposal.max_profit is not None and abs(proposal.max_profit - expected_profit) <= 0.01
            )
        else:
            economics_ok = abs(proposal.max_loss - expected_loss) <= 0.01 and proposal.max_profit is None
        add("economic_integrity", "Recomputed economics", economics_ok, "Risk is recomputed from debit, width, and quantity instead of trusting declared values.", proposal.max_loss, expected_loss)

        structure_ok, structure_detail = self._defined_risk_structure(proposal)
        add("defined_risk", "Defined-risk options only", structure_ok, structure_detail, proposal.structure, "long option or debit vertical")
        dtes = [(leg.contract.expiration - current.date()).days for leg in proposal.legs]
        dte_ok = bool(dtes) and all(self.settings.min_dte <= dte <= self.settings.max_dte for dte in dtes)
        add("dte", "Expiration window", dte_ok, "No 0DTE or near-expiry assignment risk.", min(dtes) if dtes else None, f"{self.settings.min_dte}-{self.settings.max_dte}")
        quote_ages = [max(0.0, (current - self._utc(leg.contract.quote_timestamp)).total_seconds()) for leg in proposal.legs]
        quote_age = max(quote_ages, default=float("inf"))
        quote_limit = 15 if all(leg.contract.feed == "opra" for leg in proposal.legs) else self.settings.max_quote_age_seconds
        add("quote_freshness", "Quote freshness", quote_age <= quote_limit, "Option legs require fresh quotes.", round(quote_age, 2), quote_limit)
        spread = max((leg.contract.spread_pct for leg in proposal.legs), default=float("inf"))
        add("quote_spread", "Bid/ask width", spread <= self.settings.max_quote_spread_pct, "Reject illiquid or unreliable quotes.", round(spread, 4), self.settings.max_quote_spread_pct)
        min_oi = min((leg.contract.open_interest for leg in proposal.legs), default=0)
        add("open_interest", "Open interest", min_oi >= self.settings.min_open_interest, "Each leg must meet the liquidity floor.", min_oi, self.settings.min_open_interest)
        quotes_valid = all(
            leg.contract.tradable
            and leg.contract.bid > 0
            and leg.contract.ask > leg.contract.bid
            for leg in proposal.legs
        )
        add("valid_quotes", "Tradable quotes", quotes_valid, "Every leg needs a positive, ordered two-sided quote.", quotes_valid, True)

        approved = all(item.passed for item in checks)
        failures = [item.label for item in checks if not item.passed]
        return RiskDecision(
            approved=approved,
            checks=checks,
            approved_quantity=proposal.quantity if approved else 0,
            total_risk=proposal.max_loss,
            summary="All gates passed." if approved else "Blocked by: " + ", ".join(failures),
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _defined_risk_structure(proposal: TradeProposal) -> tuple[bool, str]:
        if proposal.limit_debit <= 0 or proposal.max_loss <= 0:
            return False, "Debit and maximum loss must both be positive."
        if len(proposal.legs) == 1:
            only = proposal.legs[0]
            valid = (
                only.action is LegAction.BUY_TO_OPEN
                and only.ratio == 1
                and only.contract.underlying == proposal.underlying
            )
            return valid, "A single leg must be a 1:1 long option on the proposal underlying."
        if len(proposal.legs) != 2:
            return False, "Only one- or two-leg defined-risk structures are allowed."
        long_leg, short_leg = proposal.legs
        same_contract_family = (
            long_leg.contract.underlying == short_leg.contract.underlying == proposal.underlying
            and long_leg.contract.expiration == short_leg.contract.expiration
            and long_leg.contract.option_type is short_leg.contract.option_type
        )
        actions_ok = (
            long_leg.action is LegAction.BUY_TO_OPEN
            and short_leg.action is LegAction.SELL_TO_OPEN
            and long_leg.ratio == short_leg.ratio == 1
        )
        if long_leg.contract.option_type is OptionType.CALL:
            ordered = long_leg.contract.strike < short_leg.contract.strike
        else:
            ordered = long_leg.contract.strike > short_leg.contract.strike
        width = abs(long_leg.contract.strike - short_leg.contract.strike)
        debit_ok = 0 < proposal.limit_debit <= width * 0.60
        ok = same_contract_family and actions_ok and ordered and debit_ok
        return ok, "Atomic same-expiry vertical; debit must be no more than 60% of width."
