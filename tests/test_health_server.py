"""Unit tests for the HTTP health endpoint."""

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime

import pytest

from src.health_server import (
    get_last_run,
    record_run_completed,
    reset_state,
    start_health_server,
)


@pytest.fixture
def health_server():
    """Start a health server on an ephemeral loopback port and tear it down after."""
    reset_state()
    server = start_health_server("127.0.0.1", 0)
    yield server
    server.shutdown()
    server.server_close()
    reset_state()


def _get(server, path: str):
    """Issue a GET against the running server."""
    port = server.server_address[1]
    return urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)


class TestHealthEndpoint:
    """Tests for the served responses."""

    @pytest.mark.unit
    def test_health_returns_ok_with_null_last_run(self, health_server):
        """Before any run completes, last_run must be null rather than absent."""
        with _get(health_server, "/health") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            payload = json.loads(response.read())

        assert payload == {"status": "ok", "last_run": None}

    @pytest.mark.unit
    def test_health_reports_last_run_after_a_run(self, health_server):
        """A completed run must be reflected in the payload."""
        moment = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        record_run_completed(moment)

        with _get(health_server, "/health") as response:
            payload = json.loads(response.read())

        assert payload["status"] == "ok"
        assert payload["last_run"] == moment.isoformat()

    @pytest.mark.unit
    def test_unknown_path_returns_404(self, health_server):
        """Only /health is served; nothing else should respond 200."""
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(health_server, "/secrets")

        assert exc_info.value.code == 404

    @pytest.mark.unit
    def test_binds_loopback_only(self, health_server):
        """The default bind must not be a wildcard address."""
        assert health_server.server_address[0] == "127.0.0.1"


class TestRunState:
    """Tests for the shared last-run state."""

    @pytest.mark.unit
    def test_defaults_to_none(self):
        """State starts empty."""
        reset_state()
        assert get_last_run() is None

    @pytest.mark.unit
    def test_record_defaults_to_now(self):
        """Omitting the timestamp records the current time as an ISO string."""
        reset_state()
        before = datetime.now(UTC)
        record_run_completed()
        recorded = get_last_run()

        assert recorded is not None
        assert datetime.fromisoformat(recorded) >= before
        reset_state()

    @pytest.mark.unit
    def test_record_overwrites_previous_value(self):
        """The most recent run wins."""
        reset_state()
        record_run_completed(datetime(2026, 1, 1, tzinfo=UTC))
        record_run_completed(datetime(2026, 2, 2, tzinfo=UTC))

        assert get_last_run() == datetime(2026, 2, 2, tzinfo=UTC).isoformat()
        reset_state()
