"""Unit tests for the Docker HEALTHCHECK probe script."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "healthcheck.py"


def _load_script() -> ModuleType:
    """Import scripts/healthcheck.py, which is not an installed module."""
    spec = importlib.util.spec_from_file_location("healthcheck_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProbeHttp:
    """Tests for the HTTP probe."""

    @pytest.mark.unit
    def test_rewrites_wildcard_bind_to_loopback(self, monkeypatch):
        """A 0.0.0.0 bind is not addressable; the probe must request loopback instead."""
        script = _load_script()
        requested: list[str] = []

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def _fake_urlopen(url, timeout=None):
            requested.append(url)
            return _Response()

        monkeypatch.setattr(script.urllib.request, "urlopen", _fake_urlopen)

        assert script._probe_http("0.0.0.0", 8080) == 0
        assert requested == ["http://127.0.0.1:8080/health"]

    @pytest.mark.unit
    def test_uses_configured_host_when_not_wildcard(self, monkeypatch):
        """A specific bind address is probed as configured."""
        script = _load_script()
        requested: list[str] = []

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(
            script.urllib.request,
            "urlopen",
            lambda url, timeout=None: (requested.append(url), _Response())[1],
        )

        assert script._probe_http("127.0.0.1", 9000) == 0
        assert requested == ["http://127.0.0.1:9000/health"]

    @pytest.mark.unit
    def test_non_200_is_unhealthy(self, monkeypatch):
        """An unexpected status code must not report healthy."""
        script = _load_script()

        class _Response:
            status = 503

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(script.urllib.request, "urlopen", lambda url, timeout=None: _Response())

        assert script._probe_http("127.0.0.1", 8080) == 1

    @pytest.mark.unit
    def test_unreachable_endpoint_is_unhealthy(self, monkeypatch):
        """A connection failure must report unhealthy rather than raise."""
        script = _load_script()

        def _boom(url, timeout=None):
            raise OSError("connection refused")

        monkeypatch.setattr(script.urllib.request, "urlopen", _boom)

        assert script._probe_http("127.0.0.1", 8080) == 1


class TestMainIsQuiet:
    """Tests that the probe does not pollute Docker's health log."""

    @pytest.mark.unit
    def test_config_warnings_are_suppressed(self, tmp_path, monkeypatch, caplog):
        """
        Docker records a probe's output on every tick, so config warnings must not
        leak out of load_config — an empty env var should not be reported 12x/hour.

        Asserted via caplog rather than stdout/stderr: logging.disable() drops records
        before they reach any handler, whereas pytest's logging plugin would swallow
        anything written to the stream, making a capsys assertion vacuous.
        """
        import logging

        config_file = tmp_path / "config.yml"
        config_file.write_text(
            "tautulli_url: http://localhost:8181\n"
            "tautulli_api_key: key\n"
            "run_once: true\n"
            # defined-but-empty optional field: load_config logs a WARNING for this
            "days_back: ${PRS_TEST_EMPTY_VAR}\n"
        )
        monkeypatch.setenv("PRS_TEST_EMPTY_VAR", "")
        monkeypatch.setenv("CONFIG_PATH", str(config_file))

        script = _load_script()
        monkeypatch.setattr(script, "_probe_process", lambda: 0)

        try:
            with caplog.at_level(logging.DEBUG):
                assert script.main() == 0
            assert caplog.records == [], f"the probe emitted {len(caplog.records)} log record(s)"
        finally:
            logging.disable(logging.NOTSET)
