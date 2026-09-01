from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .engine import TradingEngine
from .models import to_primitive


def serve(engine: TradingEngine, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Serve a small local control API. It never changes execution mode at runtime."""

    if engine.settings.paper_execution_unlocked:
        raise PermissionError("The local API is disabled while paper-order execution is unlocked")

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
                self._json(engine.dashboard_state())
            elif path.startswith("/api/passports/"):
                run_id = path.rsplit("/", 1)[-1]
                report = engine.store.get(run_id)
                self._json(report or {"error": "not found"}, HTTPStatus.OK if report else HTTPStatus.NOT_FOUND)
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/cycle":
                    symbol = str(body.get("symbol") or engine.settings.underlyings[0]).upper()
                    self._json(to_primitive(engine.run_cycle(symbol)))
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

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"GlassBox Alpha local API: http://{host}:{port}")
    print("Execution mode is fixed at process startup; this API cannot unlock trading.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
