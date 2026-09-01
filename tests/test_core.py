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
from unittest.mock import patch

from glassbox_alpha.audit import AuditStore
from glassbox_alpha.broker import DemoBroker, _close_order_payload, _order_payload
from glassbox_alpha.config import Settings
from glassbox_alpha.critic import DeterministicCritic, OpenAICritic, _extract_output_text
from glassbox_alpha.engine import TradingEngine
from glassbox_alpha.indicators import build_features, ema, rsi
from glassbox_alpha.models import LegAction
from glassbox_alpha.risk import RiskKernel
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


class ConfigTests(unittest.TestCase):
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


class StrategyAndRiskTests(Fixture):
    def _candidate(self):
        account = self.broker.get_account()
        bars = self.broker.get_bars("SPY")
        features = build_features("SPY", bars)
        thesis = deterministic_thesis(features)
        chain = self.broker.get_option_chain("SPY", features.spot)
        proposal = StrategyPlanner(self.settings).plan(features, thesis, chain, account)
        assert proposal is not None
        critic = DeterministicCritic().review(proposal, features)
        return account, features, proposal, critic

    def test_planner_creates_atomic_defined_risk_vertical(self) -> None:
        _, _, proposal, _ = self._candidate()
        self.assertEqual(proposal.structure, "bull_call_debit_spread")
        self.assertEqual(len(proposal.legs), 2)
        self.assertEqual(proposal.legs[0].action, LegAction.BUY_TO_OPEN)
        self.assertEqual(proposal.legs[1].action, LegAction.SELL_TO_OPEN)
        self.assertLessEqual(proposal.max_loss, 500.0)
        self.assertGreater(proposal.max_profit or 0, 0)

    def test_level_two_falls_back_to_long_option(self) -> None:
        account, features, _, _ = self._candidate()
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
        account, features, proposal, critic = self._candidate()
        decision = RiskKernel(self.settings).evaluate(
            proposal, features, critic, account, duplicate=False, kill_switch=False
        )
        self.assertTrue(decision.approved)
        self.assertTrue(all(item.passed for item in decision.checks))

    def test_stale_quote_and_kill_switch_fail_closed(self) -> None:
        account, features, proposal, critic = self._candidate()
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

    def test_order_payload_is_one_atomic_mleg(self) -> None:
        _, _, proposal, _ = self._candidate()
        payload = _order_payload(proposal)
        self.assertEqual(payload["order_class"], "mleg")
        self.assertEqual(payload["type"], "limit")
        self.assertEqual(len(payload["legs"]), 2)
        self.assertNotIn("symbol", payload)

    def test_close_payload_reverses_both_legs_and_uses_negative_credit(self) -> None:
        _, _, proposal, _ = self._candidate()
        payload = _close_order_payload(proposal, 3.25)
        self.assertEqual(payload["limit_price"], "-3.25")
        self.assertEqual(payload["legs"][0]["position_intent"], "sell_to_close")
        self.assertEqual(payload["legs"][1]["position_intent"], "buy_to_close")


class EngineAndAuditTests(Fixture):
    def test_preview_cycle_never_submits_an_order(self) -> None:
        report = self.engine.run_cycle("SPY")
        self.assertEqual(report.status, "approved_preview")
        self.assertEqual(report.orders, [])
        self.assertTrue(report.risk and report.risk.approved)

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

    def test_kill_switch_persists_and_blocks(self) -> None:
        self.store.set_kill_switch(True)
        report = self.engine.run_cycle("SPY")
        self.assertEqual(report.status, "rejected")
        self.assertIn("Kill switch", report.risk.summary if report.risk else "")
        second_store = AuditStore(self.settings.db_path, self.settings.kill_switch_path)
        self.assertTrue(second_store.kill_switch_engaged)


class CriticTests(unittest.TestCase):
    def test_output_text_extraction(self) -> None:
        response = {"output": [{"content": [{"type": "output_text", "text": '{"verdict":"ALLOW"}'}]}]}
        self.assertEqual(json.loads(_extract_output_text(response))["verdict"], "ALLOW")

    def test_openai_network_failure_returns_veto(self) -> None:
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
            verdict = OpenAICritic("test-key", "test-model").review(proposal, features)
        self.assertEqual(verdict.verdict, "VETO")
        self.assertEqual(verdict.source, "openai_fail_closed")


if __name__ == "__main__":
    unittest.main()
