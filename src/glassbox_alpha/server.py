from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .engine import TradingEngine
from .models import to_primitive


def serve(
    engine: TradingEngine,
    host: str = "127.0.0.1",
    port: int = 8787,
    watch_interval: int = 0,
) -> None:
    """Serve the paper-agent API with authenticated, bounded strategy controls."""

    if engine.settings.paper_execution_unlocked and not engine.settings.agent_api_token:
        raise PermissionError("AGENT_API_TOKEN is required while paper-order execution is unlocked")

    class Handler(BaseHTTPRequestHandler):
        server_version = "GlassBoxAlpha/0.1"

        def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(encoded)

        def _body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                raise ValueError("request body exceeds 4096 bytes")
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _authorized(self) -> bool:
            expected = engine.settings.agent_api_token
            if not expected:
                return not engine.settings.paper_execution_unlocked
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied, f"Bearer {expected}")

        def _require_authorization(self) -> bool:
            if self._authorized():
                return True
            self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return False

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                self._json(
                    {
                        "name": "GlassBox Alpha local control API",
                        "paper_only": True,
                        "routes": ["/health", "/api/dashboard", "/api/passports/{run_id}"],
                    }
                )
            elif path == "/health":
                self._json({"ok": True, "paper_only": True, "kill_switch": engine.store.kill_switch_engaged})
            elif path == "/api/dashboard":
                if not self._require_authorization():
                    return
                self._json(engine.dashboard_state())
            elif path == "/api/control":
                if not self._require_authorization():
                    return
                self._json(engine.control.public_dict())
            elif path.startswith("/api/passports/"):
                if not self._require_authorization():
                    return
                run_id = path.rsplit("/", 1)[-1]
                report = engine.store.get(run_id)
                self._json(report or {"error": "not found"}, HTTPStatus.OK if report else HTTPStatus.NOT_FOUND)
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                if not self._require_authorization():
                    return
                body = self._body()
                if path == "/api/cycle":
                    symbol = str(body.get("symbol") or engine.settings.underlyings[0]).upper()
                    self._json(to_primitive(engine.run_cycle(symbol)))
                elif path == "/api/preview-cycle":
                    symbol = str(body.get("symbol") or engine.settings.underlyings[0]).upper()
                    strategy = str(body.get("strategy") or "auto").strip().lower()
                    self._json(to_primitive(engine.run_cycle(symbol, strategy=strategy, preview_only=True)))
                elif path == "/api/control":
                    self._json(engine.update_control(body).public_dict())
                elif path == "/api/kill-switch":
                    engaged = body.get("engaged")
                    if not isinstance(engaged, bool):
                        raise ValueError("engaged must be a boolean")
                    engine.store.set_kill_switch(engaged)
                    self._json({"kill_switch": engine.store.kill_switch_engaged})
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except RuntimeError as exc:
                self._json({"error": str(exc)}, HTTPStatus.CONFLICT)

        def log_message(self, format: str, *args: object) -> None:
            return

    stop_event = threading.Event()

    def autonomous_loop() -> None:
        # The signal uses completed five-minute bars. A shorter loop only
        # repeats identical evidence, spends API quota, and bloats the ledger.
        while not stop_event.is_set():
            try:
                for report in engine.supervise_positions():
                    print(f"{report.completed_at.isoformat()} {report.symbol} {report.status}", flush=True)
                if engine.control.enabled and engine.broker.get_account().market_open:
                    for symbol in engine.control.underlyings:
                        report = engine.run_cycle(symbol, strategy=engine.control.strategy)
                        print(f"{report.completed_at.isoformat()} {symbol} {report.status}", flush=True)
            except Exception as exc:
                print(f"Autonomous scan failed closed: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
            stop_event.wait(max(300, engine.control.scan_interval_seconds, watch_interval))

    server = ThreadingHTTPServer((host, port), Handler)
    watcher = None
    if watch_interval > 0:
        watcher = threading.Thread(target=autonomous_loop, name="glassbox-watch", daemon=True)
        watcher.start()

    print(f"GlassBox Alpha local API: http://{host}:{port}")
    print("Paper execution is fixed at startup; owner controls cannot enable live trading or bypass hard risk limits.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()
        if watcher is not None:
            watcher.join(timeout=5)
