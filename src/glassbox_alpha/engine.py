from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from .audit import AuditStore
from .broker import Broker
from .config import Settings
from .critic import Critic
from .indicators import build_features
from .models import AccountState, CycleReport, MarketFeatures, TradeProposal, proposal_from_primitive, to_primitive
from .risk import RiskKernel
from .strategy import StrategyPlanner, deterministic_thesis


class TradingEngine:
    def __init__(
        self,
        settings: Settings,
        broker: Broker,
        critic: Critic,
        store: AuditStore,
    ):
        self.settings = settings
        self.broker = broker
        self.critic = critic
        self.store = store
        self.planner = StrategyPlanner(settings)
        self.risk = RiskKernel(settings)
        self._lock = threading.Lock()
        self.last_bars: dict[str, list[dict[str, object]]] = {}

    def run_cycle(self, symbol: str | None = None) -> CycleReport:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A decision cycle is already running")
        started = datetime.now(timezone.utc)
        run_id = str(uuid4())
        selected = (symbol or self.settings.underlyings[0]).upper()
        account = None
        features = None
        thesis = None
        proposal = None
        critic = None
        risk = None
        orders = []
        submission_attempted = False
        if selected not in self.settings.underlyings:
            self._lock.release()
            raise ValueError(f"Symbol must be one of: {', '.join(self.settings.underlyings)}")
        try:
            account = self._account_with_local_state(self.broker.get_account())
            bars = self.broker.get_bars(selected, limit=max(120, self.settings.slow_ema + 10))
            self.last_bars[selected] = [
                {"timestamp": item.timestamp.isoformat(), "close": item.close}
                for item in bars[-80:]
            ]
            features = build_features(
                selected,
                bars,
                fast_period=self.settings.fast_ema,
                slow_period=self.settings.slow_ema,
            )
            thesis = deterministic_thesis(features)
            if features.data_age_seconds > self.settings.max_data_age_seconds:
                return self._record(
                    CycleReport(
                        run_id=run_id,
                        created_at=started,
                        completed_at=datetime.now(timezone.utc),
                        status="abstained_stale_data",
                        mode=self.settings.mode,
                        execution_mode=self.settings.execution_mode,
                        symbol=selected,
                        features=features,
                        thesis=thesis,
                        proposal=None,
                        critic=None,
                        risk=None,
                        notes=["The newest completed bar exceeded MAX_DATA_AGE_SECONDS; no candidate was created."],
                    )
                )
            if thesis.stance.value == "neutral":
                return self._record(
                    CycleReport(
                        run_id=run_id,
                        created_at=started,
                        completed_at=datetime.now(timezone.utc),
                        status="abstained_neutral",
                        mode=self.settings.mode,
                        execution_mode=self.settings.execution_mode,
                        symbol=selected,
                        features=features,
                        thesis=thesis,
                        proposal=None,
                        critic=None,
                        risk=None,
                        notes=["The deterministic candidate factory found no directional edge."],
                    )
                )
            if (
                abs(features.signal_score) < self.settings.min_signal_score
                or thesis.confidence < self.settings.min_confidence
            ):
                return self._record(
                    CycleReport(
                        run_id=run_id,
                        created_at=started,
                        completed_at=datetime.now(timezone.utc),
                        status="abstained_weak_signal",
                        mode=self.settings.mode,
                        execution_mode=self.settings.execution_mode,
                        symbol=selected,
                        features=features,
                        thesis=thesis,
                        proposal=None,
                        critic=None,
                        risk=None,
                        notes=[
                            "Signal or confidence was below the configured entry threshold; "
                            "the option chain and AI critic were not called."
                        ],
                    )
                )
            chain = self.broker.get_option_chain(selected, features.spot)
            proposal = self.planner.plan(features, thesis, chain, account)
            if proposal is None:
                return self._record(
                    CycleReport(
                        run_id=run_id,
                        created_at=started,
                        completed_at=datetime.now(timezone.utc),
                        status="abstained_no_contract",
                        mode=self.settings.mode,
                        execution_mode=self.settings.execution_mode,
                        symbol=selected,
                        features=features,
                        thesis=thesis,
                        proposal=None,
                        critic=None,
                        risk=None,
                        notes=["No eligible option structure could be constructed from the available chain."],
                    )
                )
            critic = self.critic.review(proposal, features)
            risk = self.risk.evaluate(
                proposal,
                features,
                critic,
                account,
                duplicate=self.store.was_submitted(proposal.proposal_id),
                kill_switch=self.store.kill_switch_engaged,
            )
            if not risk.approved:
                status = "rejected"
            elif self.settings.execution_mode == "preview":
                status = "approved_preview"
            else:
                submission_attempted = True
                orders = [self.broker.submit(proposal)]
                status = "submitted_paper"
            return self._record(
                CycleReport(
                    run_id=run_id,
                    created_at=started,
                    completed_at=datetime.now(timezone.utc),
                    status=status,
                    mode=self.settings.mode,
                    execution_mode=self.settings.execution_mode,
                    symbol=selected,
                    features=features,
                    thesis=thesis,
                    proposal=proposal,
                    critic=critic,
                    risk=risk,
                    orders=orders,
                    notes=[
                        "Paper P&L is not evidence of live fill quality or future returns.",
                        f"Option data feed: {proposal.legs[0].contract.feed}.",
                    ],
                )
            )
        except Exception as exc:
            if submission_attempted:
                self.store.set_kill_switch(True)
            status = "error_execution_unknown" if submission_attempted else "error"
            failure_note = (
                "Order submission was attempted, but its broker status is unknown. The kill switch was engaged; reconcile Alpaca before resuming."
                if submission_attempted
                else "Order submission was not attempted."
            )
            report = CycleReport(
                run_id=run_id,
                created_at=started,
                completed_at=datetime.now(timezone.utc),
                status=status,
                mode=self.settings.mode,
                execution_mode=self.settings.execution_mode,
                symbol=selected,
                features=features,
                thesis=thesis,
                proposal=proposal,
                critic=critic,
                risk=risk,
                orders=orders,
                notes=[f"{type(exc).__name__}: {str(exc)[:500]}", failure_note],
            )
            return self._record(report)
        finally:
            self._lock.release()

    def _account_with_local_state(self, account: AccountState) -> AccountState:
        account_key = account.account_id_masked or "unknown-account"
        high = self.store.update_high_watermark(account.equity, f"high_watermark:{account_key}")
        baseline_key = f"competition_balance_verified:{account_key}"
        baseline_verified = self.store.get_runtime_bool(baseline_key)
        baseline_balance_matches = any(
            abs(value - self.settings.competition_starting_balance) < 0.01
            for value in (account.equity, account.last_equity)
        )
        clean_start = (
            not baseline_verified
            and account.competition_account_match
            and account.competition_account_fresh
            and baseline_balance_matches
        )
        if clean_start:
            baseline_verified = True
            self.store.set_runtime(baseline_key, "true")
        return replace(
            account,
            high_watermark=high,
            trades_today=max(account.trades_today, self.store.submissions_today()),
            competition_balance_verified=baseline_verified,
        )

    def _record(self, report: CycleReport) -> CycleReport:
        self.store.append(report)
        return report

    def dashboard_state(self) -> dict[str, object]:
        account: dict[str, object] | None
        try:
            state = self._account_with_local_state(self.broker.get_account())
            account = to_primitive(state)
        except Exception as exc:
            account = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        return {
            "project": {
                "name": "GlassBox Alpha",
                "tagline": "An AI options agent you can audit before it trades.",
                "track": "Options Alpha Agents",
                "paper_only": True,
            },
            "settings": self.settings.public_dict(),
            "health": self.broker.health(),
            "account": account,
            "kill_switch": self.store.kill_switch_engaged,
            "stats": self.store.stats(),
            "recent": self.store.recent_meaningful(20),
            "charts": self.last_bars,
        }

    def supervise_positions(self) -> list[CycleReport]:
        """Reconcile option positions and submit whole-structure exits when policy triggers."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A decision cycle is already running")
        reports: list[CycleReport] = []
        try:
            account = self._account_with_local_state(self.broker.get_account())
            # Options only execute in the regular session. Existing broker
            # orders own the structure until terminal, including after a
            # service restart where the ephemeral audit store is empty.
            if not account.market_open or account.pending_orders > 0:
                return reports
            positions = self.broker.get_open_positions()
            if not positions:
                return reports
            entries: dict[str, dict[str, object]] = {}
            for saved in self.store.submitted_entries(1000):
                proposal_raw = saved.get("proposal")
                if isinstance(proposal_raw, dict):
                    entries.setdefault(str(proposal_raw["proposal_id"]), proposal_raw)
            for recovered in self.broker.recover_open_proposals():
                entries.setdefault(recovered.proposal_id, to_primitive(recovered))
            for proposal_raw in entries.values():
                proposal = proposal_from_primitive(proposal_raw)
                if self.store.has_status(proposal.proposal_id, "exit_submitted"):
                    continue
                held = [leg.contract.symbol in positions for leg in proposal.legs]
                if not any(held):
                    continue
                if not all(held) or not self._position_matches(proposal, positions):
                    # Direction or quantity drift can make a nominal spread unsafe to close automatically.
                    continue
                bars = self.broker.get_bars(proposal.underlying, limit=max(120, self.settings.slow_ema + 10))
                features = build_features(
                    proposal.underlying,
                    bars,
                    fast_period=self.settings.fast_ema,
                    slow_period=self.settings.slow_ema,
                )
                chain = self.broker.get_option_chain(proposal.underlying, features.spot)
                quotes = {item.symbol: item for item in chain}
                if not all(leg.contract.symbol in quotes for leg in proposal.legs):
                    continue
                if len(proposal.legs) == 1:
                    # Sell a long option at its bid so the capped exit is marketable.
                    exit_credit = quotes[proposal.legs[0].contract.symbol].bid
                else:
                    # Natural closing credit: sell the long leg at bid and buy
                    # the short leg at ask. Do not assume a midpoint fill.
                    exit_credit = max(
                        0.01,
                        quotes[proposal.legs[0].contract.symbol].bid
                        - quotes[proposal.legs[1].contract.symbol].ask,
                    )
                pnl_pct = exit_credit / proposal.limit_debit - 1
                age_minutes = (datetime.now(timezone.utc) - proposal.created_at.astimezone(timezone.utc)).total_seconds() / 60
                reason = None
                if pnl_pct >= self.settings.profit_target_pct:
                    reason = f"profit_target_{self.settings.profit_target_pct:.0%}"
                elif pnl_pct <= -self.settings.stop_loss_pct:
                    reason = f"stop_loss_{self.settings.stop_loss_pct:.0%}"
                elif age_minutes >= self.settings.max_hold_minutes:
                    reason = f"maximum_holding_time_{self.settings.max_hold_minutes}m"
                elif account.minutes_to_close is not None and account.minutes_to_close <= 35:
                    reason = "closing_bell_exit"
                elif abs(features.signal_score) < 0.15 or features.baseline_stance is not proposal.direction:
                    reason = "signal_invalidated"
                if reason is None:
                    continue
                exit_error = None
                if self.settings.execution_mode == "paper" and self.settings.paper_execution_unlocked:
                    try:
                        orders = [self.broker.submit_close(proposal, round(exit_credit, 2))]
                        status = "exit_submitted"
                    except Exception as exc:
                        self.store.set_kill_switch(True)
                        orders = []
                        status = "exit_error_unknown"
                        exit_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                else:
                    orders = []
                    status = "exit_required_preview"
                report = CycleReport(
                    run_id=str(uuid4()),
                    created_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    status=status,
                    mode=self.settings.mode,
                    execution_mode=self.settings.execution_mode,
                    symbol=proposal.underlying,
                    features=features,
                    thesis=proposal.thesis,
                    proposal=proposal,
                    critic=None,
                    risk=None,
                    orders=orders,
                    notes=[
                        f"Exit reason: {reason}.",
                        f"Observed spread return: {pnl_pct * 100:+.2f}%.",
                        f"Whole-structure limit credit: ${exit_credit:.2f}.",
                        *(
                            [
                                exit_error,
                                "Close submission status is unknown. Reconcile Alpaca before releasing the kill switch.",
                            ]
                            if exit_error
                            else []
                        ),
                    ],
                )
                self._record(report)
                reports.append(report)
                if exit_error:
                    break
            return reports
        finally:
            self._lock.release()

    @staticmethod
    def _position_matches(proposal: TradeProposal, positions: dict[str, float]) -> bool:
        for leg in proposal.legs:
            signed_quantity = proposal.quantity * leg.ratio
            if leg.action.value == "sell_to_open":
                signed_quantity *= -1
            observed = positions.get(leg.contract.symbol)
            if observed is None or abs(observed - signed_quantity) > 1e-9:
                return False
        return True
