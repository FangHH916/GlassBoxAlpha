from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .audit import AuditStore
from .broker import AlpacaBroker, build_broker
from .config import Settings
from .critic import build_critic
from .engine import TradingEngine
from .models import to_primitive
from .server import serve


def _load_environment(root: Path) -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
    except ImportError:
        return


def build_engine(project_root: Path | None = None) -> TradingEngine:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    _load_environment(root)
    settings = Settings.from_env(root)
    store = AuditStore(settings.db_path, settings.kill_switch_path)
    return TradingEngine(settings, build_broker(settings), build_critic(settings), store)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="glassbox-alpha",
        description="Auditable, paper-only AI options agent.",
    )
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run one complete decision cycle")
    run.add_argument("--symbol", default=None, help="SPY or QQQ; defaults to the first configured symbol")
    run.add_argument("--compact", action="store_true", help="Print a compact summary instead of the full passport")

    watch = commands.add_parser("watch", help="Run autonomous cycles at a fixed interval")
    watch.add_argument("--interval", type=int, default=300, help="Seconds between scans; minimum 30")
    watch.add_argument("--cycles", type=int, default=0, help="Stop after N scans; 0 means until interrupted")

    check = commands.add_parser("check", help="Read-only broker, account, and safety check")
    check.add_argument("--show-account-id", action="store_true", help="Explicitly print the full Alpaca account ID")

    commands.add_parser("kill", help="Engage the persistent new-order kill switch")
    commands.add_parser("resume", help="Release the kill switch; does not unlock paper execution")
    commands.add_parser("verify-audit", help="Verify the Trade Passport hash chain")
    commands.add_parser("supervise", help="Reconcile positions and apply deterministic exit policy")

    passport = commands.add_parser("passport", help="Print one saved Trade Passport")
    passport.add_argument("run_id")

    api = commands.add_parser("serve", help="Serve the local read/control API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8787)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        engine = build_engine()
        if args.command == "run":
            report = engine.run_cycle(args.symbol)
            if args.compact:
                print(
                    json.dumps(
                        {
                            "run_id": report.run_id,
                            "status": report.status,
                            "symbol": report.symbol,
                            "proposal_id": report.proposal.proposal_id if report.proposal else None,
                            "risk": report.risk.summary if report.risk else None,
                        },
                        indent=2,
                    )
                )
            else:
                print(json.dumps(to_primitive(report), indent=2, ensure_ascii=False))
            return 0 if not report.status.startswith("error") else 1
        if args.command == "watch":
            interval = max(30, args.interval)
            completed = 0
            try:
                while args.cycles == 0 or completed < args.cycles:
                    for exit_report in engine.supervise_positions():
                        print(
                            f"{exit_report.completed_at.isoformat()} {exit_report.symbol} {exit_report.status}",
                            flush=True,
                        )
                    for symbol in engine.settings.underlyings:
                        report = engine.run_cycle(symbol)
                        print(f"{report.completed_at.isoformat()} {symbol} {report.status}", flush=True)
                    completed += 1
                    if args.cycles == 0 or completed < args.cycles:
                        time.sleep(interval)
            except KeyboardInterrupt:
                print("Stopped. The persistent kill switch state was not changed.")
            return 0
        if args.command == "check":
            account = engine.broker.get_account()
            payload = {"health": engine.broker.health(), "account": to_primitive(account), "settings": engine.settings.public_dict()}
            if args.show_account_id and isinstance(engine.broker, AlpacaBroker):
                payload["full_account_id"] = engine.broker.full_account_id
                payload["full_account_number"] = engine.broker.full_account_number
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if args.command == "kill":
            engine.store.set_kill_switch(True)
            print("Kill switch engaged. All new candidates will be rejected.")
            return 0
        if args.command == "resume":
            engine.store.set_kill_switch(False)
            print("Kill switch released. Execution remains governed by the startup interlock.")
            return 0
        if args.command == "verify-audit":
            valid, records = engine.store.verify_chain()
            print(json.dumps({"valid": valid, "records": records}))
            return 0 if valid else 2
        if args.command == "supervise":
            reports = engine.supervise_positions()
            print(json.dumps([to_primitive(item) for item in reports], indent=2, ensure_ascii=False))
            return 0
        if args.command == "passport":
            report = engine.store.get(args.run_id)
            if report is None:
                print("Trade Passport not found.", file=sys.stderr)
                return 1
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        if args.command == "serve":
            serve(engine, args.host, args.port)
            return 0
    except (ValueError, RuntimeError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
