"""
Integration tests: full pipeline from Tautulli HTTP response → app logic → Discord webhook.

Unlike unit tests which stub at the class level, these tests only mock at the
HTTP boundary (requests.get for Tautulli, DiscordWebhook.execute for Discord),
letting all real application code run: TautulliClient, DiscordNotifier, config
validation, batch-fetch logic, date filtering, and Discord embed building.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

from src.app import run_summary
from src.config import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tautulli_ok(data: dict) -> MagicMock:
    """Build a successful mock requests.Response for a Tautulli API call."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"response": {"result": "success", "data": data}}
    return resp


def _recently_added_resp(items: list[dict]) -> MagicMock:
    return _tautulli_ok({"recently_added": items})


def _server_identity_resp(machine_id: str = "plex-server-abc") -> MagicMock:
    return _tautulli_ok({"machine_identifier": machine_id})


def _discord_resp(status_code: int = 204) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    return resp


def _ts(days_ago: float = 0.5) -> int:
    """Timestamp for an item added `days_ago` days back."""
    return int((datetime.now(UTC) - timedelta(days=days_ago)).timestamp())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config_with_discord() -> Config:
    """Minimal config with Discord enabled and no preset media_server_id."""
    return Config.model_validate(
        {
            "tautulli_url": "http://tautulli.test:8181",
            "tautulli_api_key": "test-key",
            "run_once": True,
            "discord_webhook_url": "https://discord.example/webhook/test",
            "days_back": 7,
        }
    )


@pytest.fixture
def config_no_discord() -> Config:
    """Minimal config with Discord disabled — useful for fetch-logic tests."""
    return Config.model_validate(
        {
            "tautulli_url": "http://tautulli.test:8181",
            "tautulli_api_key": "test-key",
            "run_once": True,
            "discord_webhook_url": None,
            "days_back": 7,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Full pipeline succeeds with real client code, mocked HTTP only."""

    @pytest.mark.integration
    def test_movies_and_episodes_dispatched_to_discord(self, config_with_discord, mocker):
        """
        Mixed media items (movie + episode) flow through the full pipeline.
        DiscordNotifier sends one webhook call per media-type category, so 2 items
        of different types (movie + episode) result in 2 execute() calls.
        """
        items = [
            {
                "media_type": "movie",
                "title": "Dune: Part Two",
                "added_at": _ts(0.5),
                "rating_key": "101",
            },
            {
                "media_type": "episode",
                "grandparent_title": "Severance",
                "parent_media_index": "2",
                "media_index": "1",
                "title": "Hello, Ms. Cobel",
                "added_at": _ts(1.0),
                "rating_key": "202",
            },
        ]

        # requests.get: first call = get_recently_added, second = get_server_identity
        mocker.patch(
            "requests.get",
            side_effect=[_recently_added_resp(items), _server_identity_resp()],
        )
        discord_execute = mocker.patch(
            "discord_webhook.DiscordWebhook.execute",
            return_value=_discord_resp(204),
        )

        exit_code = run_summary(config_with_discord)

        assert exit_code == 0
        # One webhook call per category: Movies (1) + TV Episodes (1) = 2
        assert discord_execute.call_count == 2

    @pytest.mark.integration
    def test_no_items_in_window_sends_no_new_items_embed(self, config_with_discord, mocker):
        """
        Items older than days_back are filtered out client-side, leaving discord_items
        empty. DiscordNotifier still sends a friendly 'no new items' embed — verify
        Discord IS called exactly once and the run exits cleanly.
        """
        old_items = [
            {"media_type": "movie", "title": "Very Old Movie", "added_at": _ts(30), "rating_key": "1"},
        ]

        # get_recently_added returns the old item; get_server_identity still needed
        # because discord_webhook_url is set and media_server_id is not pre-configured.
        mocker.patch(
            "requests.get",
            side_effect=[_recently_added_resp(old_items), _server_identity_resp()],
        )
        discord_execute = mocker.patch(
            "discord_webhook.DiscordWebhook.execute",
            return_value=_discord_resp(204),
        )

        exit_code = run_summary(config_with_discord)

        assert exit_code == 0
        # One call for the no-new-items embed
        assert discord_execute.call_count == 1

    @pytest.mark.integration
    def test_no_discord_configured_returns_zero(self, config_no_discord, mocker):
        """When discord_webhook_url is None, run completes cleanly with no HTTP to Discord."""
        items = [{"media_type": "movie", "title": "Solo Run Movie", "added_at": _ts(1), "rating_key": "5"}]
        mocker.patch("requests.get", return_value=_recently_added_resp(items))
        discord_execute = mocker.patch("discord_webhook.DiscordWebhook.execute")

        exit_code = run_summary(config_no_discord)

        assert exit_code == 0
        discord_execute.assert_not_called()


class TestErrorPropagation:
    """Network and API errors propagate correctly through the real client code."""

    @pytest.mark.integration
    def test_tautulli_connection_error_returns_1_in_run_once(self, config_no_discord, mocker):
        """
        Real TautulliClient retries DEFAULT_MAX_RETRIES times then raises.
        run_summary must catch it and return exit code 1 in run_once mode.
        """
        mocker.patch("time.sleep")  # skip retry back-off waits
        mocker.patch(
            "requests.get",
            side_effect=requests.ConnectionError("Connection refused"),
        )
        discord_execute = mocker.patch("discord_webhook.DiscordWebhook.execute")

        exit_code = run_summary(config_no_discord)

        assert exit_code == 1
        discord_execute.assert_not_called()

    @pytest.mark.integration
    def test_tautulli_api_error_result_returns_1(self, config_no_discord, mocker):
        """
        Tautulli returning result != 'success' triggers RuntimeError in real client.
        run_summary must return exit code 1.
        """
        error_resp = MagicMock()
        error_resp.status_code = 200
        error_resp.raise_for_status = MagicMock()
        error_resp.json.return_value = {"response": {"result": "error", "message": "Invalid API key"}}

        mocker.patch("time.sleep")
        mocker.patch("requests.get", return_value=error_resp)

        exit_code = run_summary(config_no_discord)

        assert exit_code == 1

    @pytest.mark.integration
    def test_discord_send_failure_returns_1_in_run_once(self, config_with_discord, mocker):
        """
        Discord HTTP failure in run_once mode must produce exit code 1.
        The real DiscordNotifier retry logic runs; all retries fail.
        """
        items = [{"media_type": "movie", "title": "Film", "added_at": _ts(1), "rating_key": "9"}]

        mocker.patch("time.sleep")
        mocker.patch(
            "requests.get",
            side_effect=[_recently_added_resp(items), _server_identity_resp()],
        )
        mocker.patch(
            "discord_webhook.DiscordWebhook.execute",
            side_effect=requests.ConnectionError("Discord unreachable"),
        )

        exit_code = run_summary(config_with_discord)

        assert exit_code == 1


class TestBatchFetchLogic:
    """Multi-batch fetch iteration — tests the real _fetch_items expansion loop."""

    @pytest.mark.integration
    def test_second_batch_requested_when_oldest_item_still_in_range(self, mocker):
        """
        When the first batch fills exactly initial_batch_size and the oldest item
        is still within days_back, the real client must request a larger second batch.
        Two get_recently_added calls expected.
        """
        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli.test:8181",
                "tautulli_api_key": "test-key",
                "run_once": True,
                "discord_webhook_url": None,
                "days_back": 7,
                "initial_batch_size": 2,  # small to force expansion
            }
        )

        # First batch: 2 items (= requested), oldest still recent → triggers expansion
        batch1 = [
            {"media_type": "movie", "title": f"Movie {i}", "added_at": _ts(0.5), "rating_key": str(i)} for i in range(2)
        ]
        # Second batch: 1 item (< 4 requested) → signals API limit reached, stop
        batch2 = [{"media_type": "movie", "title": "Last Movie", "added_at": _ts(0.5), "rating_key": "99"}]

        mocker.patch("time.sleep")  # skip inter-iteration 0.2s delay
        mock_get = mocker.patch(
            "requests.get",
            side_effect=[_recently_added_resp(batch1), _recently_added_resp(batch2)],
        )

        exit_code = run_summary(config)

        assert exit_code == 0
        assert mock_get.call_count == 2  # exactly 2 Tautulli calls
