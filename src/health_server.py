"""Minimal HTTP health endpoint for container liveness probes.

Exposes ``GET /health`` on a daemon thread so an orchestrator can distinguish a
running scheduler from a wedged one — the process-based check it replaces only
proves that a PID exists.

The server binds to loopback by default and is disabled unless explicitly
enabled, so it adds no network exposure out of the box.
"""

import json
import logging
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

HEALTH_PATH = "/health"

_state_lock = threading.Lock()
_last_run: str | None = None


def record_run_completed(when: datetime | None = None) -> None:
    """
    Record the timestamp of a run that finished building its summary.

    Recorded even when notification delivery failed: the field reports scheduler
    liveness, so a Discord outage should not make a healthy container look stale.

    Args:
        when: Completion time; defaults to now (UTC)
    """
    global _last_run
    timestamp = (when or datetime.now(UTC)).isoformat()
    with _state_lock:
        _last_run = timestamp


def get_last_run() -> str | None:
    """Return the last recorded run timestamp, or None if no run has completed."""
    with _state_lock:
        return _last_run


def reset_state() -> None:
    """Clear the recorded run timestamp (used by tests)."""
    global _last_run
    with _state_lock:
        _last_run = None


class _HealthRequestHandler(BaseHTTPRequestHandler):
    """Serves GET /health and nothing else."""

    # Silences BaseHTTPRequestHandler's stderr logging in favour of our logger.
    def log_message(self, format: str, *args: object) -> None:
        logger.debug("health request: %s", format % args)

    def do_GET(self) -> None:
        """Answer health probes; anything else gets a bare 404."""
        if self.path != HEALTH_PATH:
            self.send_error(404)
            return

        body = json.dumps({"status": "ok", "last_run": get_last_run()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_health_server(host: str, port: int) -> ThreadingHTTPServer:
    """
    Start the health server on a daemon thread.

    Args:
        host: Interface to bind (default configuration binds loopback only)
        port: TCP port to listen on; 0 selects an ephemeral port

    Returns:
        The running server, so callers can shut it down or read server_address

    Raises:
        OSError: If the address cannot be bound
    """
    server = ThreadingHTTPServer((host, port), _HealthRequestHandler)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    logger.info("🩺 Health endpoint listening on http://%s:%d%s", host, server.server_address[1], HEALTH_PATH)
    return server
