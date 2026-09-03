from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from glassbox_alpha.audit import AuditStore
from glassbox_alpha.broker import AlpacaBroker, DemoBroker, _close_order_payload, _order_payload
from glassbox_alpha.config import Settings
from glassbox_alpha.critic import DeepSeekCritic, DeterministicCritic, _extract_output_text
from glassbox_alpha.engine import TradingEngine
from glassbox_alpha.indicators import build_features, ema, rsi
from glassbox_alpha.models import LegAction, Stance
from glassbox_alpha.risk import RiskKernel
from glassbox_alpha.server import serve
from glassbox_alpha.strategy import StrategyPlanner, deterministic_thesis


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(project_root=self.root, db_path=self.root / "audit.db", kill_switch_path=self.root / "kill")
        self.broker = DemoBroker(self.settings)
        self.store = AuditStore(self.settings.db_path, self.settings.kill_switch_path)
        self.engine = TradingEngine(self.settings, self.broker, DeterministicCritic(), self.store)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def candidate(self):
        account = self.broker.get_account()
        bars = self.broker.get_bars("SPY")
        features = build_features("SPY", bars)
        thesis = deterministic_thesis(features)
        chain = self.broker.get_option_chain("SPY", features.spot)
        proposal = StrategyPlanner(self.settings).plan(features, thesis, chain, account)
        assert proposal is not None
        critic = DeterministicCritic().review(proposal, features)
        return account, features, proposal, critic


class IndicatorTests(unittest.TestCase):
    def test_ema_and_rsi(self) -> None:
        values = [float(item) for item in range(1, 70)]
        self.assertGreater(ema(values, 10), ema(values, 30))
        self.assertEqual(rsi(values), 100.0)

    def test_demo_features_are_bullish_and_fresh(self) -> None:
        settings = Settings(project_root=Path.cwd())
        broker = DemoBroker(settings)
        features = build_features("SPY", broker.get_bars("SPY"))
        self.assertGreaterEqual(features.signal_score, settings.min_signal_score)
        self.assertLess(features.data_age_seconds, 10)

    def test_demo_clock_refreshes_after_idle_time(self) -> None:
        settings = Settings(project_root=Path.cwd())
        broker = DemoBroker(settings)
        broker._now = datetime.now(timezone.utc) - timedelta(minutes=10)
        features = build_features("SPY", broker.get_bars("SPY"))
        chain = broker.get_option_chain("SPY", features.spot)
        self.assertLess(features.data_age_seconds, 10)
        self.assertLess((datetime.now(timezone.utc) - chain[0].quote_timestamp).total_seconds(), 10)


class ConfigTests(unittest.TestCase):
    def test_legacy_primary_universe_gets_validated_expansion(self) -> None:
        with patch.dict(os.environ, {"UNDERLYINGS": "SPY,QQQ"}, clear=True):
            settings = Settings.from_env(Path.cwd())
        self.assertEqual(settings.underlyings, ("SPY", "QQQ", "GLD", "IWM"))

    def test_live_mode_is_not_supported(self) -> None:
        with patch.dict(os.environ, {"BROKER_MODE": "live"}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env(Path.cwd())

    def test_paper_interlock_requires_all_four_conditions(self) -> None:
        base = Settings(project_root=Path.cwd(), mode="alpaca", execution_mode="paper", allow_paper_orders=True)
        self.assertFalse(base.paper_execution_unlocked)
        unlocked = replace(
            base,
            paper_confirmation="I_UNDERSTAND_PAPER_ONLY",
            competition_account_id="account-id",
        )
        self.assertTrue(unlocked.paper_execution_unlocked)

    def test_invalid_risk_and_naive_competition_time_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Settings(project_root=Path.cwd(), max_quote_spread_pct=0).validate()
        with self.assertRaises(ValueError):
            Settings(project_root=Path.cwd(), competition_start_utc="2026-08-28T15:00:00").validate()

    def test_paper_api_requires_shared_token(self) -> None:
        root = Path.cwd()
        settings = Settings(
            project_root=root,
            mode="alpaca",
            execution_mode="paper",
            allow_paper_orders=True,
            paper_confirmation="I_UNDERSTAND_PAPER_ONLY",
            competition_account_id="competition-account",
            db_path=root / "data" / "unused-test.db",
            kill_switch_path=root / "data" / "unused-test-kill",
        )
        broker = DemoBroker(settings)
        with tempfile.TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "audit.db", Path(directory) / "kill")
            engine = TradingEngine(settings, broker, DeterministicCritic(), store)
            with self.assertRaises(PermissionError):
                serve(engine, port=0)


class StrategyAndRiskTests(Fixture):
    def test_planner_creates_atomic_defined_risk_vertical(self) -> None:
        _, _, proposal, _ = self.candidate()
        self.assertEqual(proposal.structure, "bull_call_debit_spread")
        self.assertEqual(len(proposal.legs), 2)
        self.assertEqual(proposal.legs[0].action, LegAction.BUY_TO_OPEN)
        self.assertEqual(proposal.legs[1].action, LegAction.SELL_TO_OPEN)
        natural_debit = round(proposal.legs[0].contract.ask - proposal.legs[1].contract.bid, 2)
        self.assertEqual(proposal.limit_debit, natural_debit)
        self.assertLessEqual(proposal.max_loss, 500.0)
        self.assertGreater(proposal.max_profit or 0, 0)

    def test_level_two_falls_back_to_long_option(self) -> None:
        account, features, _, _ = self.candidate()
        chain = self.broker.get_option_chain("SPY", features.spot)
        proposal = StrategyPlanner(self.settings).plan(
            features,
            deterministic_thesis(features),
            chain,
            replace(account, options_trading_level=2),
        )
        assert proposal is not None
        self.assertEqual(len(proposal.legs), 1)
        self.assertTrue(proposal.structure.startswith("long_"))

    def test_clean_candidate_passes_every_gate(self) -> None:
        account, features, proposal, critic = self.candidate()
        decision = RiskKernel(self.settings).evaluate(
            proposal, features, critic, account, duplicate=False, kill_switch=False
        )
        self.assertTrue(decision.approved)
        self.assertTrue(all(item.passed for item in decision.checks))
        self.assertEqual(len(decision.checks), 33)

    def test_tampered_economics_and_symbol_are_rejected(self) -> None:
        account, features, proposal, critic = self.candidate()
        tampered_leg = replace(
            proposal.legs[0],
            contract=replace(proposal.legs[0].contract, underlying="QQQ"),
        )
        tampered = replace(proposal, max_loss=1.0, legs=[tampered_leg, *proposal.legs[1:]])
        decision = RiskKernel(self.settings).evaluate(
            tampered, features, critic, account, duplicate=False, kill_switch=False
        )
        failed = {item.code for item in decision.checks if not item.passed}
        self.assertIn("candidate_symbol", failed)
        self.assertIn("economic_integrity", failed)
        self.assertFalse(decision.approved)

    def test_stale_quote_and_kill_switch_fail_closed(self) -> None:
        account, features, proposal, critic = self.candidate()
        stale_legs = [
            replace(
                leg,
                contract=replace(
                    leg.contract,
                    quote_timestamp=datetime.now(timezone.utc) - timedelta(seconds=120),
                ),
            )
            for leg in proposal.legs
        ]
        stale = replace(proposal, legs=stale_legs)
        decision = RiskKernel(self.settings).evaluate(
            stale, features, critic, account, duplicate=False, kill_switch=True
        )
        failed = {item.code for item in decision.checks if not item.passed}
        self.assertFalse(decision.approved)
        self.assertIn("quote_freshness", failed)
        self.assertIn("kill_switch", failed)

    def test_pending_broker_order_blocks_a_new_entry(self) -> None:
        account, features, proposal, critic = self.candidate()
        decision = RiskKernel(self.settings).evaluate(
            proposal,
            features,
            critic,
            replace(account, pending_orders=1),
            duplicate=False,
            kill_switch=False,
        )
        self.assertFalse(decision.approved)
        pending = next(check for check in decision.checks if check.code == "pending_orders")
        self.assertFalse(pending.passed)

    def test_order_payload_is_one_atomic_mleg(self) -> None:
        _, _, proposal, _ = self.candidate()
        payload = _order_payload(proposal)
        self.assertEqual(payload["order_class"], "mleg")
        self.assertEqual(payload["type"], "limit")
        self.assertEqual(len(payload["legs"]), 2)
        self.assertNotIn("symbol", payload)

    def test_close_payload_reverses_both_legs_and_uses_negative_credit(self) -> None:
        _, _, proposal, _ = self.candidate()
        payload = _close_order_payload(proposal, 3.25)
        self.assertEqual(payload["limit_price"], "-3.25")
        self.assertEqual(payload["legs"][0]["position_intent"], "sell_to_close")
        self.assertEqual(payload["legs"][1]["position_intent"], "buy_to_close")

    def test_alpaca_sdk_entry_and_exit_requests_match_installed_client(self) -> None:
        _, _, proposal, _ = self.candidate()

        class Trading:
            def __init__(self):
                self.requests = []

            def submit_order(self, order_data):
                self.requests.append(order_data)
                return SimpleNamespace(
                    id=f"order-{len(self.requests)}",
                    client_order_id=order_data.client_order_id,
                    status="accepted",
                    submitted_at=datetime.now(timezone.utc),
                )

        broker = AlpacaBroker.__new__(AlpacaBroker)
        broker.settings = self.settings
        broker.trading = Trading()
        entry = broker._submit_sdk(proposal)
        close = broker._submit_close_sdk(proposal, 3.25)
        self.assertEqual(entry.status, "accepted")
        self.assertEqual(close.status, "accepted")
        self.assertEqual(len(broker.trading.requests[0].legs), 2)
        self.assertEqual(float(broker.trading.requests[1].limit_price), -3.25)


class EngineAndAuditTests(Fixture):
    def test_preview_cycle_never_submits_an_order(self) -> None:
        report = self.engine.run_cycle("SPY")
        self.assertEqual(report.status, "approved_preview")
        self.assertEqual(report.orders, [])
        self.assertTrue(report.risk and report.risk.approved)

    def test_ambiguous_submission_engages_kill_switch_and_blocks_retry(self) -> None:
        settings = replace(
            self.settings,
            mode="alpaca",
            execution_mode="paper",
            allow_paper_orders=True,
            paper_confirmation="I_UNDERSTAND_PAPER_ONLY",
            competition_account_id="competition-account",
        )

        class AmbiguousBroker(DemoBroker):
            def submit(self, proposal):
                raise TimeoutError("broker response timed out")

        engine = TradingEngine(settings, AmbiguousBroker(settings), DeterministicCritic(), self.store)
        report = engine.run_cycle("SPY")
        self.assertEqual(report.status, "error_execution_unknown")
        self.assertTrue(self.store.kill_switch_engaged)
        assert report.proposal is not None
        self.assertTrue(self.store.was_submitted(report.proposal.proposal_id))
        self.assertIn("reconcile Alpaca", " ".join(report.notes))

    def test_trade_passports_form_a_valid_hash_chain(self) -> None:
        self.engine.run_cycle("SPY")
        self.engine.run_cycle("QQQ")
        self.assertEqual(self.store.verify_chain(), (True, 2))
        with closing(sqlite3.connect(self.settings.db_path)) as connection:
            connection.execute("UPDATE decisions SET payload_json = '{}' WHERE sequence = 1")
            connection.commit()
        valid, broken_at = self.store.verify_chain()
        self.assertFalse(valid)
        self.assertEqual(broken_at, 1)

    def test_dashboard_hides_stale_noise_without_deleting_audit_records(self) -> None:
        original = self.broker.get_bars

        def stale_bars(symbol: str, limit: int = 120):
            return [replace(bar, timestamp=bar.timestamp - timedelta(hours=2)) for bar in original(symbol, limit)]

        with patch.object(self.broker, "get_bars", side_effect=stale_bars):
            self.engine.run_cycle("SPY")
        self.engine.run_cycle("QQQ")
        self.assertEqual(len(self.store.recent()), 2)
        self.assertEqual(len(self.store.recent_meaningful()), 1)
        self.assertEqual(self.store.verify_chain(), (True, 2))

    def test_stale_market_data_abstains_before_candidate_creation(self) -> None:
        original = self.broker.get_bars

        def stale_bars(symbol: str, limit: int = 120):
            return [replace(bar, timestamp=bar.timestamp - timedelta(hours=2)) for bar in original(symbol, limit)]

        with patch.object(self.broker, "get_bars", side_effect=stale_bars):
            report = self.engine.run_cycle("SPY")
        self.assertEqual(report.status, "abstained_stale_data")
        self.assertIsNone(report.proposal)
        self.assertIsNone(report.critic)

    def test_weak_signal_abstains_before_option_chain_and_critic(self) -> None:
        bars = self.broker.get_bars("SPY")
        strong = build_features("SPY", bars)
        weak = replace(
            strong,
            signal_score=self.settings.min_signal_score - 0.01,
            baseline_stance=Stance.BULLISH,
        )
        with (
            patch("glassbox_alpha.engine.build_features", return_value=weak),
            patch.object(self.broker, "get_option_chain", side_effect=AssertionError("option chain should not run")),
        ):
            report = self.engine.run_cycle("SPY")
        self.assertEqual(report.status, "abstained_weak_signal")
        self.assertIsNone(report.proposal)
        self.assertIsNone(report.critic)

    def test_kill_switch_persists_and_blocks(self) -> None:
        self.store.set_kill_switch(True)
        report = self.engine.run_cycle("SPY")
        self.assertEqual(report.status, "rejected")
        self.assertIn("Kill switch", report.risk.summary if report.risk else "")
        second_store = AuditStore(self.settings.db_path, self.settings.kill_switch_path)
        self.assertTrue(second_store.kill_switch_engaged)

    def test_account_baseline_and_high_watermark_are_namespaced(self) -> None:
        first = replace(self.broker.get_account(), account_id_masked="AAAA•••1111")
        second = replace(
            self.broker.get_account(),
            account_id_masked="BBBB•••2222",
            competition_account_match=False,
        )
        self.assertTrue(self.engine._account_with_local_state(first).competition_balance_verified)
        self.assertFalse(self.engine._account_with_local_state(second).competition_balance_verified)
        self.assertNotEqual(
            self.store.get_runtime_float("high_watermark:AAAA•••1111", 0),
            0,
        )

    def test_exit_requires_exact_position_direction_and_quantity(self) -> None:
        _, _, proposal, _ = self.candidate()
        exact = {
            proposal.legs[0].contract.symbol: float(proposal.quantity),
            proposal.legs[1].contract.symbol: float(-proposal.quantity),
        }
        self.assertTrue(self.engine._position_matches(proposal, exact))
        self.assertFalse(self.engine._position_matches(proposal, {**exact, proposal.legs[1].contract.symbol: 1.0}))
        self.assertFalse(
            self.engine._position_matches(
                proposal,
                {**exact, proposal.legs[0].contract.symbol: float(proposal.quantity + 1)},
            )
        )


class CriticTests(unittest.TestCase):
    def test_output_text_extraction(self) -> None:
        response = {
            "output": [
                {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "internal analysis"}]},
                {"type": "message", "content": [{"type": "output_text", "text": '{"verdict":"ALLOW"}'}]},
            ]
        }
        self.assertEqual(json.loads(_extract_output_text(response))["verdict"], "ALLOW")

    def test_deepseek_network_failure_returns_veto(self) -> None:
        settings = Settings(project_root=Path.cwd())
        broker = DemoBroker(settings)
        account = broker.get_account()
        features = build_features("SPY", broker.get_bars("SPY"))
        proposal = StrategyPlanner(settings).plan(
            features,
            deterministic_thesis(features),
            broker.get_option_chain("SPY", features.spot),
            account,
        )
        assert proposal is not None
        with patch("urllib.request.urlopen", side_effect=TimeoutError("offline")):
            verdict = DeepSeekCritic("test-key", "test-model").review(proposal, features)
        self.assertEqual(verdict.verdict, "VETO")
        self.assertEqual(verdict.source, "deepseek_fail_closed")

    def test_deepseek_missing_evidence_fails_closed(self) -> None:
        settings = Settings(project_root=Path.cwd())
        broker = DemoBroker(settings)
        features = build_features("SPY", broker.get_bars("SPY"))
        proposal = StrategyPlanner(settings).plan(
            features,
            deterministic_thesis(features),
            broker.get_option_chain("SPY", features.spot),
            broker.get_account(),
        )
        assert proposal is not None
        output = {
            "candidate_id": proposal.proposal_id,
            "verdict": "ALLOW",
            "risk_flags": [],
            "evidence_ids": [f"candidate:{proposal.proposal_id}"],
            "thesis": "Insufficient citation set.",
            "invalidated_if": "Signal changes.",
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"output_text": json.dumps(output)}).encode()

        with patch("urllib.request.urlopen", return_value=Response()):
            verdict = DeepSeekCritic("test-key", "test-model").review(proposal, features)
        self.assertEqual(verdict.verdict, "VETO")
        self.assertEqual(verdict.source, "deepseek_fail_closed")

    def test_deepseek_receives_exact_allowed_evidence_ids(self) -> None:
        settings = Settings(project_root=Path.cwd())
        broker = DemoBroker(settings)
        features = build_features("SPY", broker.get_bars("SPY"))
        proposal = StrategyPlanner(settings).plan(
            features,
            deterministic_thesis(features),
            broker.get_option_chain("SPY", features.spot),
            broker.get_account(),
        )
        assert proposal is not None
        expected = [
            f"bars:{features.symbol}:{features.timestamp.isoformat()}",
            f"candidate:{proposal.proposal_id}",
        ]
        output = {
            "candidate_id": proposal.proposal_id,
            "verdict": "ALLOW",
            "risk_flags": [],
            "evidence_ids": expected,
            "thesis": "Candidate matches the supplied evidence.",
            "invalidated_if": "Signal changes.",
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"output_text": json.dumps(output)}).encode()

        with patch("urllib.request.urlopen", return_value=Response()) as request:
            verdict = DeepSeekCritic("test-key", "test-model").review(proposal, features)
        sent = json.loads(request.call_args.args[0].data.decode())
        evidence = json.loads(sent["input"])
        self.assertEqual(evidence["allowed_evidence_ids"], expected)
        self.assertEqual(sent["reasoning"], {"effort": "none"})
        self.assertIn("trend-pullback", sent["instructions"])
        self.assertIn("do not require reversal confirmation", sent["instructions"])
        self.assertIn("never approves execution", sent["instructions"])
        self.assertIn("are debit spreads", sent["instructions"])
        self.assertEqual(verdict.verdict, "ALLOW")


if __name__ == "__main__":
    unittest.main()
