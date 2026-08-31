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
