#!/usr/bin/env python3
"""Docker HEALTHCHECK probe.

Probes the HTTP health endpoint when it is enabled, and otherwise falls back to
the process check this replaced — so a container running with the default
(disabled) configuration still reports its liveness correctly.

Exits 0 when healthy, 1 otherwise. Uses only the standard library, so the image
needs no curl.
"""

import logging
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, "/app/src")

from config import DEFAULT_CONFIG_PATH, load_config

PROCESS_PATTERN = "python.*app.py"
TIMEOUT_SECONDS = 5


def _probe_http(host: str, port: int) -> int:
    """Return 0 if the health endpoint answers 200, else 1."""
    # Loopback is not addressable from outside the container, so when the server
    # binds 0.0.0.0 we still probe it locally.
    target = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{target}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            return 0 if response.status == 200 else 1
    except Exception as e:
        print(f"health endpoint unreachable at {url}: {e}", file=sys.stderr)
        return 1


def _probe_process() -> int:
    """Return 0 if the application process is running, else 1."""
    return 0 if subprocess.run(["pgrep", "-f", PROCESS_PATTERN], capture_output=True).returncode == 0 else 1


def main() -> int:
    """Choose the probe based on configuration and run it."""
    # load_config logs warnings (e.g. env vars defined but empty). Docker captures a
    # probe's output into the health log on every tick, so a liveness check must stay
    # silent unless it has something to say about health itself.
    logging.disable(logging.CRITICAL)

    try:
        config = load_config(os.getenv("CONFIG_PATH", DEFAULT_CONFIG_PATH))
    except Exception as e:
        print(f"could not load configuration, falling back to process check: {e}", file=sys.stderr)
        return _probe_process()

    if not config.enable_healthcheck or config.run_once:
        return _probe_process()

    return _probe_http(config.health_host, config.health_port)


if __name__ == "__main__":
    sys.exit(main())
