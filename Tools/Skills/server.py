"""
AiNiee Skills HTTP Server

A lightweight REST server that exposes the Skills framework over HTTP.
No MCP, no FastAPI, no uvicorn — just the Python standard library.

Endpoints:
    GET  /skills              — List all skills with metadata
    GET  /skills/<name>       — Describe a specific skill
    POST /skills/<name>       — Execute a skill with arguments
    GET  /health              — Health check

Usage:
    python Tools/Skills/server.py [--port PORT] [--host HOST]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict
from urllib.parse import urlparse


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Tools.Skills.skills import build_registry


SKILLS_AUTH_HEADER = "X-AiNiee-Skills-Auth"


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


class SkillsHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Skills server."""

    # Shared across all instances
    registry = build_registry()
    auth_token: str = ""
    require_auth: bool = True
    allow_origin: str = ""

    def log_message(self, format: str, *args: Any) -> None:
        """Log to stderr so stdout stays clean for potential JSONL consumers."""
        sys.stderr.write(f"[Skills] {args[0]} {args[1]} {args[2]}\n")

    def _send_cors_headers(self) -> None:
        if not self.allow_origin:
            return
        self.send_header("Access-Control-Allow-Origin", self.allow_origin)
        self.send_header("Vary", "Origin")

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = _json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str, code: str = "") -> None:
        self._send_json({"error": message, "error_code": code}, status)

    def _read_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            f"Content-Type, {SKILLS_AUTH_HEADER}",
        )
        self.end_headers()

    def _is_authorized(self) -> bool:
        if not self.require_auth:
            return True
        token = self.auth_token
        provided = self.headers.get(SKILLS_AUTH_HEADER, "")
        return bool(token) and secrets.compare_digest(str(provided), token)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._send_json({
                "status": "ok",
                "service": "ainiee-skills",
                "skills_count": self.registry.count,
            })
            return

        if path == "/skills":
            self._send_json({
                "skills": self.registry.list_skills(),
                "count": self.registry.count,
            })
            return

        if path.startswith("/skills/"):
            name = path[len("/skills/"):]
            try:
                meta = self.registry.get_skill_meta(name)
                self._send_json(meta)
            except Exception as e:
                self._send_error(404, str(e), "UNKNOWN_SKILL")
            return

        self._send_error(404, f"Not found: {path}", "NOT_FOUND")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/skills/"):
            if not self._is_authorized():
                self._send_error(401, "Missing or invalid Skills auth token.", "UNAUTHORIZED")
                return
            name = path[len("/skills/"):]
            body = self._read_body()
            args = body.get("args", body)
            try:
                result = self.registry.execute(name, args)
                self._send_json(result.to_dict())
            except Exception as e:
                self._send_error(500, str(e), "EXECUTION_ERROR")
            return

        self._send_error(404, f"Not found: {path}", "NOT_FOUND")


def run_server(
    host: str = "127.0.0.1",
    port: int = 8766,
    *,
    auth_token: str | None = None,
    require_auth: bool = True,
    allow_origin: str = "",
) -> None:
    """Start the Skills HTTP server."""
    if require_auth and not auth_token:
        auth_token = os.environ.get("AINIEE_SKILLS_AUTH_TOKEN") or secrets.token_urlsafe(24)
    SkillsHTTPHandler.auth_token = auth_token or ""
    SkillsHTTPHandler.require_auth = require_auth
    SkillsHTTPHandler.allow_origin = allow_origin or ""

    server = HTTPServer((host, port), SkillsHTTPHandler)
    sys.stderr.write(
        f"[Skills] Server starting on http://{host}:{port}\n"
        f"[Skills] Endpoints:\n"
        f"[Skills]   GET  /health       — Health check\n"
        f"[Skills]   GET  /skills       — List all skills\n"
        f"[Skills]   GET  /skills/<name> — Describe a skill\n"
        f"[Skills]   POST /skills/<name> — Execute a skill\n"
    )
    if require_auth:
        sys.stderr.write(
            f"[Skills] POST auth header: {SKILLS_AUTH_HEADER}: {SkillsHTTPHandler.auth_token}\n"
        )
    else:
        sys.stderr.write("[Skills] WARNING: HTTP auth is disabled.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("[Skills] Shutting down...\n")
        server.server_close()


def run_server_detached(
    host: str = "127.0.0.1",
    port: int = 8766,
    *,
    auth_token: str | None = None,
    require_auth: bool = True,
    allow_origin: str = "",
) -> HTTPServer:
    """Start server in a way that can be stopped programmatically."""
    if require_auth and not auth_token:
        auth_token = os.environ.get("AINIEE_SKILLS_AUTH_TOKEN") or secrets.token_urlsafe(24)
    SkillsHTTPHandler.auth_token = auth_token or ""
    SkillsHTTPHandler.require_auth = require_auth
    SkillsHTTPHandler.allow_origin = allow_origin or ""

    server = HTTPServer((host, port), SkillsHTTPHandler)
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    actual_host, actual_port = server.server_address
    sys.stderr.write(f"[Skills] Server started (detached) on http://{actual_host}:{actual_port}\n")
    return server


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AiNiee Skills HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address.")
    parser.add_argument("--port", type=int, default=8766, help="Port number.")
    parser.add_argument("--auth-token", default=None, help="HTTP auth token.")
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable HTTP auth. Only use on trusted local machines.",
    )
    parser.add_argument(
        "--allow-origin",
        default="",
        help="Optional CORS Access-Control-Allow-Origin value.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        run_server(
            host=args.host,
            port=args.port,
            auth_token=args.auth_token,
            require_auth=not args.no_auth,
            allow_origin=args.allow_origin,
        )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
