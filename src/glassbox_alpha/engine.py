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
from .models import AccountState, CycleReport, MarketFeatures, proposal_from_primitive, to_primitive
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
            orders = []
            if not risk.approved:
                status = "rejected"
            elif self.settings.execution_mode == "preview":
                status = "approved_preview"
            else:
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
            report = CycleReport(
                run_id=run_id,
                created_at=started,
                completed_at=datetime.now(timezone.utc),
                status="error",
                mode=self.settings.mode,
                execution_mode=self.settings.execution_mode,
                symbol=selected,
                features=None,
                thesis=None,
                proposal=None,
                critic=None,
                risk=None,
                notes=[f"{type(exc).__name__}: {str(exc)[:500]}", "The system failed closed; no order was sent."],
            )
            return self._record(report)
        finally:
            self._lock.release()

    def _account_with_local_state(self, account: AccountState) -> AccountState:
        high = self.store.update_high_watermark(account.equity)
        baseline_verified = self.store.get_runtime_bool("competition_balance_verified")
        clean_start = (
            not baseline_verified
            and account.open_option_positions == 0
            and abs(account.equity - self.settings.competition_starting_balance) < 0.01
        )
        if clean_start:
            baseline_verified = True
            self.store.set_runtime("competition_balance_verified", "true")
        return replace(
            account,
            high_watermark=high,
            trades_today=self.store.submissions_today(),
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
            "recent": self.store.recent(20),
            "charts": self.last_bars,
        }

    def supervise_positions(self) -> list[CycleReport]:
        """Reconcile option positions and submit whole-structure exits when policy triggers."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A decision cycle is already running")
        reports: list[CycleReport] = []
        try:
            positions = self.broker.get_open_positions()
            if not positions:
                return reports
            entries: dict[str, dict[str, object]] = {}
            for saved in self.store.recent(200):
                proposal_raw = saved.get("proposal")
                if saved.get("status") == "submitted_paper" and isinstance(proposal_raw, dict):
                    entries.setdefault(str(proposal_raw["proposal_id"]), proposal_raw)
            account = self._account_with_local_state(self.broker.get_account())
            for proposal_raw in entries.values():
                proposal = proposal_from_primitive(proposal_raw)
                if self.store.has_status(proposal.proposal_id, "exit_submitted"):
                    continue
                held = [leg.contract.symbol in positions for leg in proposal.legs]
                if not any(held):
                    continue
                if not all(held):
                    # A partial or externally changed position must be handled manually; never create a naked leg.
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
                    exit_credit = quotes[proposal.legs[0].contract.symbol].midpoint
                else:
                    exit_credit = max(
                        0.01,
                        quotes[proposal.legs[0].contract.symbol].midpoint
                        - quotes[proposal.legs[1].contract.symbol].midpoint,
                    )
                pnl_pct = exit_credit / proposal.limit_debit - 1
                age_minutes = (datetime.now(timezone.utc) - proposal.created_at.astimezone(timezone.utc)).total_seconds() / 60
                reason = None
                if pnl_pct >= 0.35:
                    reason = "profit_target_35pct"
                elif pnl_pct <= -0.25:
                    reason = "stop_loss_25pct"
                elif age_minutes >= 120:
                    reason = "maximum_holding_time_120m"
                elif account.minutes_to_close is not None and account.minutes_to_close <= 35:
                    reason = "closing_bell_exit"
                elif abs(features.signal_score) < 0.15 or features.baseline_stance is not proposal.direction:
                    reason = "signal_invalidated"
                if reason is None:
                    continue
                if self.settings.execution_mode == "paper" and self.settings.paper_execution_unlocked:
                    orders = [self.broker.submit_close(proposal, round(exit_credit, 2))]
                    status = "exit_submitted"
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
                    ],
                )
                self._record(report)
                reports.append(report)
            return reports
        finally:
            self._lock.release()
