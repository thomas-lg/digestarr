"""Unit tests for app module formatting logic."""

import importlib.metadata
import logging
from datetime import UTC, datetime
from typing import cast

import pytest
import requests

import src.app as src_app
from src.app import (
    _build_discord_payload,
    _build_media_source,
    _filter_excluded_media_types,
    _format_display_title,
    _get_config_path,
    _send_discord_notification,
    main,
    run_summary,
)
from src.config import Config
from src.media_source import MediaItem
from src.tautulli_client import TautulliClient


class TestFormatDisplayTitle:
    """Tests for _format_display_title function."""

    @pytest.mark.unit
    def test_format_episode_with_valid_numbers(self):
        """Test formatting episode with valid season/episode numbers."""
        item: MediaItem = {
            "media_type": "episode",
            "grandparent_title": "Breaking Bad",
            "parent_media_index": "5",
            "media_index": "14",
            "title": "Ozymandias",
        }
        result = _format_display_title(item)
        assert result == "Breaking Bad - S05E14 - Ozymandias"

    @pytest.mark.unit
    def test_format_episode_with_integer_numbers(self):
        """Test formatting episode with integer season/episode numbers."""
        item: MediaItem = {
            "media_type": "episode",
            "grandparent_title": "The Wire",
            "parent_media_index": 1,
            "media_index": 1,
            "title": "The Target",
        }
        result = _format_display_title(item)
        assert result == "The Wire - S01E01 - The Target"

    @pytest.mark.unit
    def test_format_episode_with_missing_numbers(self):
        """Test formatting episode with missing season/episode numbers."""
        item: MediaItem = {
            "media_type": "episode",
            "grandparent_title": "Unknown Show",
            "parent_media_index": "?",
            "media_index": "?",
            "title": "Episode Title",
        }
        result = _format_display_title(item)
        assert result == "Unknown Show - S00E00 - Episode Title"

    @pytest.mark.unit
    def test_format_episode_with_invalid_numbers(self):
        """Test formatting episode with non-numeric season/episode values."""
        item: MediaItem = {
            "media_type": "episode",
            "grandparent_title": "Show Name",
            "parent_media_index": "invalid",
            "media_index": "abc",
            "title": "Episode",
        }
        result = _format_display_title(item)
        assert result == "Show Name - SinvalidEabc - Episode"

    @pytest.mark.unit
    def test_format_episode_missing_fields(self):
        """Test formatting episode with missing fields."""
        item: MediaItem = {
            "media_type": "episode",
            # Missing grandparent_title, parent_media_index, etc.
        }
        result = _format_display_title(item)
        assert "Unknown Show" in result
        assert "Unknown Episode" in result

    @pytest.mark.unit
    def test_format_season(self):
        """Test formatting season."""
        item: MediaItem = {"media_type": "season", "parent_title": "The Sopranos", "media_index": "3"}
        result = _format_display_title(item)
        assert result == "The Sopranos - Season 3"

    @pytest.mark.unit
    def test_format_season_missing_fields(self):
        """Test formatting season with missing fields."""
        item: MediaItem = {"media_type": "season", "media_index": "1"}
        result = _format_display_title(item)
        assert "Unknown Show" in result
        assert "Season 1" in result

    @pytest.mark.unit
    def test_format_show_with_year(self):
        """Test formatting show with year."""
        item: MediaItem = {"media_type": "show", "title": "Stranger Things", "year": "2016"}
        result = _format_display_title(item)
        assert result == "Stranger Things (2016)"

    @pytest.mark.unit
    def test_format_show_without_year(self):
        """Test formatting show without year."""
        item: MediaItem = {"media_type": "show", "title": "New Show"}
        result = _format_display_title(item)
        assert result == "New Show (New Series)"

    @pytest.mark.unit
    def test_format_track(self):
        """Test formatting music track."""
        item: MediaItem = {
            "media_type": "track",
            "grandparent_title": "The Beatles",
            "parent_title": "Abbey Road",
            "title": "Come Together",
        }
        result = _format_display_title(item)
        assert result == "The Beatles - Abbey Road - Come Together"

    @pytest.mark.unit
    def test_format_track_missing_fields(self):
        """Test formatting track with missing fields."""
        item: MediaItem = {"media_type": "track", "title": "Song Name"}
        result = _format_display_title(item)
        assert "Unknown Artist" in result
        assert "Unknown Album" in result
        assert "Song Name" in result

    @pytest.mark.unit
    def test_format_album(self):
        """Test formatting music album."""
        item: MediaItem = {
            "media_type": "album",
            "parent_title": "Pink Floyd",
            "title": "Dark Side of the Moon",
        }
        result = _format_display_title(item)
        assert result == "Pink Floyd - Dark Side of the Moon"

    @pytest.mark.unit
    def test_format_album_missing_fields(self):
        """Test formatting album with missing fields."""
        item: MediaItem = {"media_type": "album", "title": "Album Name"}
        result = _format_display_title(item)
        assert "Unknown Artist" in result
        assert "Album Name" in result

    @pytest.mark.unit
    def test_format_movie_with_year(self):
        """Test formatting movie with year."""
        item: MediaItem = {"media_type": "movie", "title": "The Shawshank Redemption", "year": "1994"}
        result = _format_display_title(item)
        assert result == "The Shawshank Redemption (1994)"

    @pytest.mark.unit
    def test_format_movie_without_year(self):
        """Test formatting movie without year."""
        item: MediaItem = {"media_type": "movie", "title": "New Movie"}
        result = _format_display_title(item)
        assert result == "New Movie"

    @pytest.mark.unit
    def test_format_movie_missing_fields(self):
        """Test formatting movie with missing fields."""
        item: MediaItem = {"media_type": "movie"}
        result = _format_display_title(item)
        assert result == "Unknown Movie"

    @pytest.mark.unit
    def test_format_unknown_media_type(self):
        """Test formatting unknown media type."""
        item: MediaItem = {"media_type": "unknown_type", "title": "Some Media"}
        result = _format_display_title(item)
        assert result == "Some Media"

    @pytest.mark.unit
    def test_format_no_media_type(self):
        """Test formatting when media_type is missing."""
        item: MediaItem = {"title": "Some Title"}
        result = _format_display_title(item)
        assert result == "Some Title"

    @pytest.mark.unit
    def test_format_unknown_type_without_title(self):
        """Test that the else-branch returns 'Unknown' when no title is present."""
        item: MediaItem = {"media_type": "unknown"}
        result = _format_display_title(item)
        assert result == "Unknown"


class TestRunSummary:
    """Tests for run_summary behavior and operational guarantees."""

    @pytest.mark.unit
    def test_run_summary_fails_in_run_once_when_discord_send_fails(self, monkeypatch):
        """Discord delivery errors should produce non-zero exit code in one-shot mode."""

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                timestamp = int(datetime.now(UTC).timestamp())
                return {"recently_added": [{"media_type": "movie", "title": "Movie", "added_at": timestamp}]}

            def get_server_identity(self):
                return {"machine_identifier": "server-id"}

        class StubDiscordNotifier:
            def __init__(self, webhook_url, media_server_url, media_server_id):
                self.webhook_url = webhook_url
                self.media_server_url = media_server_url
                self.media_server_id = media_server_id

            def send_summary(self, media_items, days_back, total_count):
                raise requests.RequestException("network timeout")

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))
        monkeypatch.setattr("src.app.DiscordNotifier", StubDiscordNotifier)

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": "https://discord.example/webhook",
            }
        )

        assert run_summary(config) == 1

    @pytest.mark.unit
    def test_run_summary_keeps_scheduled_mode_non_fatal_on_discord_error(self, monkeypatch):
        """Discord errors should not fail scheduled executions."""

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                timestamp = int(datetime.now(UTC).timestamp())
                return {"recently_added": [{"media_type": "movie", "title": "Movie", "added_at": timestamp}]}

            def get_server_identity(self):
                return {"machine_identifier": "server-id"}

        class StubDiscordNotifier:
            def __init__(self, webhook_url, media_server_url, media_server_id):
                self.webhook_url = webhook_url
                self.media_server_url = media_server_url
                self.media_server_id = media_server_id

            def send_summary(self, media_items, days_back, total_count):
                raise requests.RequestException("network timeout")

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))
        monkeypatch.setattr("src.app.DiscordNotifier", StubDiscordNotifier)

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": False,
                "discord_webhook_url": "https://discord.example/webhook",
            }
        )

        assert run_summary(config) == 0

    @pytest.mark.unit
    def test_run_summary_limits_info_output_per_media_type(self, monkeypatch, caplog):
        """INFO logging should show at most 10 entries per media type."""

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                timestamp = int(datetime.now(UTC).timestamp())
                movies = [{"media_type": "movie", "title": f"Movie {i}", "added_at": timestamp} for i in range(1, 13)]
                shows = [{"media_type": "show", "title": f"Show {i}", "added_at": timestamp} for i in range(1, 12)]
                return {"recently_added": movies + shows}

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
            }
        )

        caplog.set_level("INFO")
        assert run_summary(config) == 0

        added_lines = [record.message for record in caplog.records if record.message.startswith("➕")]
        assert len(added_lines) == 20
        assert any("movie: 2" in record.message and "show: 1" in record.message for record in caplog.records)

    @pytest.mark.unit
    def test_run_summary_stops_when_api_returns_fewer_items_than_requested(self, monkeypatch):
        """Fetching should stop when the API returns fewer items than requested (hit its limit)."""
        call_counts = {"n": 0}

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                call_counts["n"] += 1
                timestamp = int(datetime.now(UTC).timestamp())
                # Always return 5 items regardless of how many were requested
                return {
                    "recently_added": [
                        {"media_type": "movie", "title": f"Movie {i}", "added_at": timestamp} for i in range(5)
                    ]
                }

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
                "initial_batch_size": 100,  # request 100, get 5 → stop after first batch
            }
        )

        assert run_summary(config) == 0
        assert call_counts["n"] == 1  # exactly one API call

    @pytest.mark.unit
    def test_run_summary_expands_batch_when_oldest_item_still_in_range(self, monkeypatch):
        """Fetching should expand the batch size when the oldest returned item is still within the date range."""
        call_counts = {"n": 0}
        timestamps = {
            # First batch: all items are recent (within range), oldest still in range → expand
            1: int(datetime.now(UTC).timestamp()),
            # Second batch: oldest item is old (outside range) → stop
            2: 0,
        }

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                call_counts["n"] += 1
                oldest_ts = timestamps.get(call_counts["n"], 0)
                items = [
                    {"media_type": "movie", "title": f"Movie {i}", "added_at": int(datetime.now(UTC).timestamp())}
                    for i in range(count - 1)
                ]
                # Last item has the controlled timestamp
                items.append({"media_type": "movie", "title": "Oldest", "added_at": oldest_ts})
                return {"recently_added": items}

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))
        monkeypatch.setattr("src.tautulli_client.time.sleep", lambda _: None)

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
                "initial_batch_size": 5,
            }
        )

        assert run_summary(config) == 0
        assert call_counts["n"] == 2  # expanded once, then stopped

    @pytest.mark.unit
    def test_run_summary_stops_at_max_iterations(self, monkeypatch, caplog):
        """Fetching should stop and warn when the max iteration guardrail (50) is reached."""

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                # Always return exactly `count` items, all recent → always triggers another iteration
                timestamp = int(datetime.now(UTC).timestamp())
                return {
                    "recently_added": [
                        {"media_type": "movie", "title": f"Movie {i}", "added_at": timestamp} for i in range(count)
                    ]
                }

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))
        monkeypatch.setattr("src.tautulli_client.time.sleep", lambda _: None)

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
                "initial_batch_size": 1,
            }
        )

        caplog.set_level("WARNING")
        assert run_summary(config) == 0
        assert any("max fetch iterations" in r.message.lower() for r in caplog.records)

    @pytest.mark.unit
    def test_run_summary_stops_when_max_fetch_count_reached(self, monkeypatch):
        """Iterative fetching should stop once the max fetch count guardrail is reached."""

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                timestamp = int(datetime.now(UTC).timestamp())
                return {
                    "recently_added": [
                        {"media_type": "movie", "title": f"Movie {i}", "added_at": timestamp} for i in range(count)
                    ]
                }

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))
        monkeypatch.setattr("src.tautulli_client.time.sleep", lambda _seconds: None)

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
                "initial_batch_size": 9990,
            }
        )

        assert run_summary(config) == 0


class TestMain:
    """Tests for main() startup behavior: banner and version resolution."""

    @staticmethod
    def _stub_config():
        return Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
            }
        )

    @pytest.mark.unit
    def test_main_prints_banner_and_logs_version(self, monkeypatch, caplog, capsys):
        """main() prints the ASCII banner to stdout and logs the version."""
        monkeypatch.setattr("src.app._get_config_path", lambda: "/config.yml")
        monkeypatch.setattr("src.app.setup_logging", lambda *a, **kw: None)
        monkeypatch.setattr("src.app.get_bootstrap_log_level", lambda _: "INFO")
        monkeypatch.setattr("importlib.metadata.version", lambda _pkg: "1.2.3")
        monkeypatch.setattr("src.app.load_config", lambda _: TestMain._stub_config())
        monkeypatch.setattr("src.app.run_summary", lambda _: 0)

        caplog.set_level("INFO", logger="app")
        main()

        stdout = capsys.readouterr().out
        assert "PRS" in stdout or "Digestarr" in stdout, "Expected banner in stdout"
        assert "v1.2.3" in stdout

        log_records = [r.message for r in caplog.records if "Digestarr" in r.message]
        assert log_records, "Expected version log line"
        assert "v1.2.3" in log_records[0]

    @pytest.mark.unit
    def test_main_falls_back_to_unknown_version_when_package_not_installed(self, monkeypatch, caplog, capsys):
        """main() falls back to 'unknown' in both banner and log when package is not installed."""
        monkeypatch.setattr("src.app._get_config_path", lambda: "/config.yml")
        monkeypatch.setattr("src.app.setup_logging", lambda *a, **kw: None)
        monkeypatch.setattr("src.app.get_bootstrap_log_level", lambda _: "INFO")

        def _raise_not_found(_pkg):
            raise importlib.metadata.PackageNotFoundError("digestarr")

        monkeypatch.setattr("importlib.metadata.version", _raise_not_found)
        monkeypatch.setattr("src.app.load_config", lambda _: TestMain._stub_config())
        monkeypatch.setattr("src.app.run_summary", lambda _: 0)

        caplog.set_level("INFO", logger="app")
        main()

        stdout = capsys.readouterr().out
        assert "unknown" in stdout, "Expected 'unknown' version in printed banner"

        log_records = [r.message for r in caplog.records if "Digestarr" in r.message]
        assert log_records, "Expected version log line"
        assert "unknown" in log_records[0]


class TestBuildDiscordPayloadDebugPath:
    """Tests for _build_discord_payload debug-enabled path and rating_key assignment."""

    @pytest.mark.unit
    def test_debug_path_logs_each_item(self, caplog):
        """When the app logger is at DEBUG level, each item should be debug-logged."""
        from src.app import _build_discord_payload

        timestamp = int(datetime.now(UTC).timestamp())
        items: list[MediaItem] = [
            {"media_type": "movie", "title": "Movie X", "added_at": timestamp},
        ]
        # Enable DEBUG on the 'app' logger so debug_enabled = True inside _build_discord_payload
        app_logger = logging.getLogger("app")
        orig = app_logger.level
        app_logger.setLevel(logging.DEBUG)
        caplog.set_level(logging.DEBUG, logger="app")
        try:
            result = _build_discord_payload(items)
        finally:
            app_logger.setLevel(orig)

        assert len(result) == 1
        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG and "Movie X" in r.message]
        assert debug_msgs

    @pytest.mark.unit
    def test_rating_key_included_in_discord_item_when_present(self):
        """Items with rating_key should have it transferred to the DiscordMediaItem."""
        from src.app import _build_discord_payload

        timestamp = int(datetime.now(UTC).timestamp())
        items: list[MediaItem] = [
            {"media_type": "movie", "title": "Movie With Key", "added_at": timestamp, "rating_key": 42},
        ]
        result = _build_discord_payload(items)
        assert len(result) == 1
        assert result[0].get("rating_key") == 42


class TestGetConfigPath:
    """Tests for _get_config_path env var resolution."""

    @pytest.mark.unit
    def test_returns_env_var_when_set(self, monkeypatch):
        """Should return CONFIG_PATH env var value when it is set."""
        monkeypatch.setenv("CONFIG_PATH", "/custom/path/config.yml")
        assert _get_config_path() == "/custom/path/config.yml"

    @pytest.mark.unit
    def test_returns_default_when_env_var_absent(self, monkeypatch):
        """Should return DEFAULT_CONFIG_PATH when CONFIG_PATH is not set."""
        monkeypatch.delenv("CONFIG_PATH", raising=False)
        from src.config import DEFAULT_CONFIG_PATH

        assert _get_config_path() == DEFAULT_CONFIG_PATH


class TestBuildDiscordPayloadSuppression:
    """Tests for _build_discord_payload suppression log when >10 items per type."""

    @pytest.mark.unit
    def test_suppression_log_fired_for_overflow_items(self, caplog):
        """Items exceeding DEFAULT_INFO_DISPLAY_LIMIT per type should log a suppression summary."""
        from src.app import DEFAULT_INFO_DISPLAY_LIMIT

        timestamp = int(datetime.now(UTC).timestamp())
        items: list[MediaItem] = [
            {"media_type": "movie", "title": f"Movie {i}", "added_at": timestamp}
            for i in range(DEFAULT_INFO_DISPLAY_LIMIT + 3)  # 3 over the limit → suppressed count = 3
        ]

        # Force the "app" logger to INFO so debug_enabled is False inside _build_discord_payload
        app_logger = logging.getLogger("app")
        old_level = app_logger.level
        app_logger.setLevel(logging.INFO)
        caplog.set_level("INFO", logger="app")
        try:
            result = _build_discord_payload(items)
        finally:
            app_logger.setLevel(old_level)

        assert len(result) == DEFAULT_INFO_DISPLAY_LIMIT + 3
        suppression_msgs = [r.message for r in caplog.records if "additional items hidden" in r.message]
        assert suppression_msgs, "Expected suppression summary log line"
        assert "movie: 3" in suppression_msgs[0]


class TestSendDiscordNotification:
    """Tests for _send_discord_notification error-handling paths."""

    def _make_config(self, *, media_server_id=None, run_once=True):
        return Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": run_once,
                "discord_webhook_url": "https://discord.example/webhook",
                "media_server_id": media_server_id,
            }
        )

    @pytest.mark.unit
    def test_request_exception_fetching_server_id_warns_and_continues(self, monkeypatch, caplog):
        """RequestException during server ID auto-fetch should warn and not abort."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_server_identity(self):
                raise requests.RequestException("timeout")

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                return True

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        caplog.set_level("WARNING", logger="app")
        result = _send_discord_notification(
            self._make_config(media_server_id=None, run_once=False), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 0
        assert any("Network error while fetching" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_value_error_fetching_server_id_warns_and_continues(self, monkeypatch, caplog):
        """ValueError during server ID auto-fetch should warn and not abort."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_server_identity(self):
                raise ValueError("bad response")

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                return True

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        caplog.set_level("WARNING", logger="app")
        result = _send_discord_notification(
            self._make_config(media_server_id=None, run_once=False), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 0
        assert any("Invalid response from Tautulli" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_empty_machine_identifier_logs_warning(self, monkeypatch, caplog):
        """Empty machine_identifier in auto-detected identity should log a warning."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_server_identity(self):
                return {"machine_identifier": ""}

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                return True

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        caplog.set_level("WARNING", logger="app")
        result = _send_discord_notification(
            self._make_config(media_server_id=None), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 0
        assert any("Could not auto-detect" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_discord_request_exception_run_once_returns_1(self, monkeypatch):
        """RequestException from Discord send should return 1 in run_once mode."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            pass

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                raise requests.RequestException("net error")

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        result = _send_discord_notification(
            self._make_config(media_server_id="srv", run_once=True), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 1

    @pytest.mark.unit
    def test_discord_value_error_run_once_returns_1(self, monkeypatch):
        """ValueError from Discord send should return 1 in run_once mode."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            pass

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                raise ValueError("invalid config")

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        result = _send_discord_notification(
            self._make_config(media_server_id="srv", run_once=True), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 1

    @pytest.mark.unit
    def test_discord_generic_exception_run_once_returns_1(self, monkeypatch):
        """Unhandled exception from Discord send should return 1 in run_once mode."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            pass

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                raise RuntimeError("unexpected boom")

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        result = _send_discord_notification(
            self._make_config(media_server_id="srv", run_once=True), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 1

    @pytest.mark.unit
    def test_send_summary_false_run_once_returns_1(self, monkeypatch):
        """send_summary returning False in run_once mode should return 1."""

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            pass

        class StubNotifier:
            def __init__(self, *a, **kw):
                pass

            def send_summary(self, *a, **kw):
                return False

        monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
        result = _send_discord_notification(
            self._make_config(media_server_id="srv", run_once=True), cast(TautulliClient, StubTautulli()), [], 7, 0
        )
        assert result == 1

    @pytest.mark.unit
    def test_discord_errors_non_fatal_in_scheduled_mode(self, monkeypatch):
        """All Discord errors should return 0 (non-fatal) in scheduled mode."""
        for exc in [requests.RequestException("e"), ValueError("v"), RuntimeError("r")]:
            the_exc = exc

            class StubTautulli(TautulliClient):
                def __init__(self, **kwargs):
                    super().__init__(
                        "http://tautulli:8181",
                        "key",
                        initial_batch_size=kwargs.get("initial_batch_size"),
                    )

                pass

            class StubNotifier:
                def __init__(self, *a, **kw):
                    pass

                def send_summary(self, *a, _exc=the_exc, **kw):
                    raise _exc

            monkeypatch.setattr("src.app.DiscordNotifier", StubNotifier)
            result = _send_discord_notification(
                self._make_config(media_server_id="srv", run_once=False), cast(TautulliClient, StubTautulli()), [], 7, 0
            )
            assert result == 0


class TestRunSummaryFetchErrors:
    """Tests for run_summary exception handling from the media source fetch."""

    def _base_config(self):
        return Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
            }
        )

    @pytest.mark.unit
    def test_network_error_in_fetch_returns_1(self, monkeypatch):
        """RequestException from the fetch should cause run_summary to return 1."""

        def raise_net_error(*a, **kw):
            raise requests.RequestException("timeout")

        monkeypatch.setattr("src.app.TautulliClient.get_items_added_since", raise_net_error)
        assert run_summary(self._base_config()) == 1

    @pytest.mark.unit
    def test_value_error_in_fetch_returns_1(self, monkeypatch):
        """ValueError from the fetch should cause run_summary to return 1."""

        def raise_val_error(*a, **kw):
            raise ValueError("bad data")

        monkeypatch.setattr("src.app.TautulliClient.get_items_added_since", raise_val_error)
        assert run_summary(self._base_config()) == 1

    @pytest.mark.unit
    def test_unexpected_exception_in_fetch_returns_1(self, monkeypatch):
        """Unexpected exception from the fetch should cause run_summary to return 1."""

        def raise_unexpected(*a, **kw):
            raise RuntimeError("something broke")

        monkeypatch.setattr("src.app.TautulliClient.get_items_added_since", raise_unexpected)
        assert run_summary(self._base_config()) == 1


class TestMainAppVersionFromEnv:
    """Test main() when APP_VERSION env var is set."""

    @pytest.mark.unit
    def test_main_uses_app_version_env_var_when_set(self, monkeypatch, capsys):
        """main() should use APP_VERSION env var instead of importlib.metadata."""
        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": None,
            }
        )
        monkeypatch.setattr("src.app._get_config_path", lambda: "/config.yml")
        monkeypatch.setattr("src.app.setup_logging", lambda *a, **kw: None)
        monkeypatch.setattr("src.app.get_bootstrap_log_level", lambda _: "INFO")
        monkeypatch.setenv("APP_VERSION", "9.9.9")
        monkeypatch.setattr("src.app.load_config", lambda _: config)
        monkeypatch.setattr("src.app.run_summary", lambda _: 0)

        main()

        stdout = capsys.readouterr().out
        assert "v9.9.9" in stdout


class TestSendDiscordNotificationDefensiveRaise:
    """Test _send_discord_notification defensive guard when webhook_url is None."""

    @pytest.mark.unit
    def test_none_webhook_url_config_raises_and_returns_1(self, monkeypatch):
        """Passing a config whose discord_webhook_url is None should hit the guard and return 1."""
        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                # discord_webhook_url intentionally NOT set → None
            }
        )

        class StubTautulli(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            pass

        # Manually set media_server_id to skip the auto-detect block
        config_with_sid = config.model_copy(update={"media_server_id": "srv"})
        result = _send_discord_notification(config_with_sid, cast(TautulliClient, StubTautulli()), [], 7, 0)
        assert result == 1


class TestMainScheduledAndFatalPaths:
    """Tests for main() scheduled mode dispatch and fatal load_config failure."""

    @pytest.mark.unit
    def test_scheduled_mode_calls_run_scheduled_with_cron(self, monkeypatch, capsys):
        """main() with run_once=False should call run_scheduled with the cron_schedule."""
        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": False,
                "cron_schedule": "0 9 * * *",
            }
        )
        scheduled_calls: list[str] = []

        monkeypatch.setattr("src.app._get_config_path", lambda: "/config.yml")
        monkeypatch.setattr("src.app.setup_logging", lambda *a, **kw: None)
        monkeypatch.setattr("src.app.get_bootstrap_log_level", lambda _: "INFO")
        monkeypatch.setattr("importlib.metadata.version", lambda _: "1.0.0")
        monkeypatch.setattr("src.app.load_config", lambda _: config)
        monkeypatch.setattr(
            "src.app.run_scheduled",
            lambda task_func, cron: scheduled_calls.append(cron) or 0,
        )

        result = main()

        assert result == 0
        assert scheduled_calls == ["0 9 * * *"]

    @pytest.mark.unit
    def test_load_config_exception_returns_1(self, monkeypatch, capsys):
        """main() should return 1 and log a fatal error when load_config raises."""

        def raise_config_error(_path):
            raise ValueError("broken YAML")

        monkeypatch.setattr("src.app._get_config_path", lambda: "/config.yml")
        monkeypatch.setattr("src.app.setup_logging", lambda *a, **kw: None)
        monkeypatch.setattr("src.app.get_bootstrap_log_level", lambda _: "INFO")
        monkeypatch.setattr("importlib.metadata.version", lambda _: "1.0.0")
        monkeypatch.setattr("src.app.load_config", raise_config_error)

        result = main()

        assert result == 1


class TestFilterExcludedMediaTypes:
    """Tests for _filter_excluded_media_types."""

    @staticmethod
    def _items() -> list[MediaItem]:
        return [
            cast(MediaItem, {"media_type": "movie", "title": "Inception", "added_at": 1}),
            cast(MediaItem, {"media_type": "track", "title": "Song", "added_at": 2}),
            cast(MediaItem, {"media_type": "album", "title": "Record", "added_at": 3}),
        ]

    @pytest.mark.unit
    def test_empty_exclusion_returns_input_unchanged(self):
        """Test that no exclusions is a no-op, preserving current behaviour."""
        items = self._items()
        assert _filter_excluded_media_types(items, []) is items

    @pytest.mark.unit
    def test_drops_excluded_types(self):
        """Test that only the excluded media types are removed."""
        result = _filter_excluded_media_types(self._items(), ["track", "album"])
        assert [item["media_type"] for item in result] == ["movie"]

    @pytest.mark.unit
    def test_matching_is_case_insensitive(self):
        """Test that a Tautulli payload with unexpected casing is still matched."""
        items = [cast(MediaItem, {"media_type": "TRACK", "title": "Song", "added_at": 1})]
        assert _filter_excluded_media_types(items, ["track"]) == []

    @pytest.mark.unit
    def test_excluding_everything_yields_empty_list(self):
        """Test the degenerate case where nothing survives the filter."""
        result = _filter_excluded_media_types(self._items(), ["movie", "track", "album"])
        assert result == []

    @pytest.mark.unit
    def test_logs_dropped_counts(self, caplog):
        """Test that the summary line reports what was dropped."""
        with caplog.at_level(logging.INFO):
            _filter_excluded_media_types(self._items(), ["track", "album"])
        assert "Excluded 2 item(s) by media type" in caplog.text
        assert "album: 1" in caplog.text
        assert "track: 1" in caplog.text

    @pytest.mark.unit
    def test_no_log_when_nothing_matches(self, caplog):
        """Test that a configured exclusion matching nothing stays silent."""
        with caplog.at_level(logging.INFO):
            result = _filter_excluded_media_types(self._items(), ["episode"])
        assert len(result) == 3
        assert "Excluded" not in caplog.text


class TestRunSummaryExcludesMediaTypes:
    """End-to-end test that run_summary honours excluded_media_types."""

    @pytest.mark.unit
    def test_excluded_items_reach_neither_notifier_nor_totals(self, monkeypatch, caplog):
        """Excluded items must be absent from the payload, the total_count and the final log."""

        class StubTautulliClient(TautulliClient):
            def __init__(self, **kwargs):
                super().__init__(
                    "http://tautulli:8181",
                    "key",
                    initial_batch_size=kwargs.get("initial_batch_size"),
                )

            def get_recently_added(self, days=7, count=100):
                timestamp = int(datetime.now(UTC).timestamp())
                return {
                    "recently_added": [
                        {"media_type": "movie", "title": "Inception", "added_at": timestamp},
                        {"media_type": "track", "title": "Song", "added_at": timestamp},
                        {"media_type": "album", "title": "Record", "added_at": timestamp},
                    ]
                }

            def get_server_identity(self):
                return {"machine_identifier": "server-id"}

        sent: dict[str, object] = {}

        class StubDiscordNotifier:
            def __init__(self, webhook_url, media_server_url, media_server_id):
                pass

            def send_summary(self, media_items, days_back, total_count):
                sent["media_items"] = media_items
                sent["total_count"] = total_count
                return True

        monkeypatch.setattr("src.app.TautulliClient", lambda *args, **kwargs: StubTautulliClient(**kwargs))
        monkeypatch.setattr("src.app.DiscordNotifier", StubDiscordNotifier)

        config = Config.model_validate(
            {
                "tautulli_url": "http://tautulli:8181",
                "tautulli_api_key": "secret",
                "run_once": True,
                "discord_webhook_url": "https://discord.example/webhook",
                "excluded_media_types": ["track", "album"],
            }
        )

        with caplog.at_level(logging.INFO):
            assert run_summary(config) == 0

        media_items = cast(list[dict[str, object]], sent["media_items"])
        assert [item["type"] for item in media_items] == ["movie"]
        # The count handed to the notifier and the closing log line must both
        # reflect the post-filter total, not the raw Tautulli count.
        assert sent["total_count"] == 1
        assert "✅ Run complete: 1 items" in caplog.text
        assert "Song" not in caplog.text


class TestHealthServerStartup:
    """Tests for wiring the health endpoint into main()."""

    def _config(self, **overrides):
        base = {
            "tautulli_url": "http://tautulli:8181",
            "tautulli_api_key": "secret",
            "run_once": False,
            "cron_schedule": "0 16 * * SUN",
        }
        base.update(overrides)
        return Config.model_validate(base)

    @pytest.mark.unit
    def test_not_started_when_disabled(self, monkeypatch):
        """Default configuration must open no socket at all."""
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr("src.app.load_config", lambda path: self._config())
        monkeypatch.setattr("src.app.start_health_server", lambda host, port: calls.append((host, port)))
        monkeypatch.setattr("src.app.run_scheduled", lambda task, cron: 0)

        assert main() == 0
        assert calls == []

    @pytest.mark.unit
    def test_started_in_scheduled_mode_when_enabled(self, monkeypatch):
        """Enabling it starts the server with the configured host and port."""
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "src.app.load_config",
            lambda path: self._config(enable_healthcheck=True, health_host="127.0.0.1", health_port=9999),
        )
        monkeypatch.setattr("src.app.start_health_server", lambda host, port: calls.append((host, port)))
        monkeypatch.setattr("src.app.run_scheduled", lambda task, cron: 0)

        assert main() == 0
        assert calls == [("127.0.0.1", 9999)]

    @pytest.mark.unit
    def test_not_started_in_run_once_mode(self, monkeypatch):
        """One-shot mode exits immediately, so a health server would be pointless."""
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "src.app.load_config",
            lambda path: self._config(run_once=True, enable_healthcheck=True),
        )
        monkeypatch.setattr("src.app.start_health_server", lambda host, port: calls.append((host, port)))
        monkeypatch.setattr("src.app.run_summary", lambda config: 0)

        assert main() == 0
        assert calls == []

    @pytest.mark.unit
    def test_bind_failure_is_fatal(self, monkeypatch, capsys):
        """An unusable port must fail loudly rather than run without the promised probe."""

        def _boom(host, port):
            raise OSError("address already in use")

        monkeypatch.setattr("src.app.load_config", lambda path: self._config(enable_healthcheck=True))
        monkeypatch.setattr("src.app.start_health_server", _boom)
        monkeypatch.setattr("src.app.run_scheduled", lambda task, cron: 0)

        assert main() == 1
        # main() reconfigures logging handlers, so the record is asserted on the
        # stream rather than via caplog.
        assert "Could not start health endpoint" in capsys.readouterr().out


class TestBuildMediaSource:
    """Tests for selecting the media source from configuration."""

    @staticmethod
    def _config(**overrides):
        base = {
            "tautulli_url": "http://tautulli:8181",
            "tautulli_api_key": "secret",
            "run_once": True,
        }
        base.update(overrides)
        return Config.model_validate(base)

    @pytest.mark.unit
    def test_defaults_to_tautulli(self):
        """Unconfigured installs keep reading from Tautulli."""
        source = _build_media_source(self._config())

        # Asserted against the class src.app itself imported: under PYTHONPATH=src,
        # src.tautulli_client and tautulli_client are distinct module objects, so
        # isinstance against the test's own import would always be False.
        assert isinstance(source, src_app.TautulliClient)
        assert source.base_url == "http://tautulli:8181"

    @pytest.mark.unit
    def test_selects_tracearr_when_configured(self):
        """media_source: tracearr builds the Tracearr client with its own credentials."""
        source = _build_media_source(
            self._config(
                media_source="tracearr",
                tracearr_url="http://tracearr:3000/",
                tracearr_api_key="trr_pub_x",
                media_server_id="abc",
            )
        )

        assert isinstance(source, src_app.TracearrClient)
        assert source.base_url == "http://tracearr:3000"

    @pytest.mark.unit
    def test_warns_when_tracearr_has_no_media_server_id(self, caplog):
        """
        Tracearr cannot report the Plex machine identifier, so links silently vanish
        unless media_server_id is set. That deserves a warning, not silence.
        """
        with caplog.at_level(logging.WARNING):
            _build_media_source(
                self._config(
                    media_source="tracearr",
                    tracearr_url="http://tracearr:3000",
                    tracearr_api_key="trr_pub_x",
                )
            )

        assert "cannot auto-detect the media server id" in caplog.text
