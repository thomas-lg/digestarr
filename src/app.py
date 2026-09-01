"""Main application entrypoint: orchestrates Tautulli fetching and Discord notification."""

import importlib.metadata
import logging
import os
import re
import sys
from datetime import UTC, datetime, timedelta

import requests

from config import (
    DEFAULT_CONFIG_PATH,
    MEDIA_SOURCE_TRACEARR,
    Config,
    get_bootstrap_log_level,
    load_config,
    sync_missing_config_keys,
)
from discord_client import DiscordMediaItem, DiscordNotifier
from health_server import record_run_completed, start_health_server
from logging_config import setup_logging
from media_source import MediaItem, MediaSourceClient, ServerIdentity
from scheduler import run_scheduled
from tautulli_client import TautulliClient
from tracearr_client import TracearrClient

logger = logging.getLogger("app")

# Constants
DEFAULT_INFO_DISPLAY_LIMIT = 10  # Number of items to display in INFO log level
MAX_FETCH_ITERATIONS = 50
MAX_FETCH_COUNT = 10000


def _get_config_path() -> str:
    """Resolve config file path from env var override or default container path."""
    return os.getenv("CONFIG_PATH", DEFAULT_CONFIG_PATH)


def _build_media_source(config: Config) -> MediaSourceClient:
    """
    Build the media source client the configuration selects.

    Args:
        config: Application configuration

    Returns:
        A client satisfying the MediaSourceClient protocol
    """
    if config.media_source == MEDIA_SOURCE_TRACEARR:
        if not config.plex_server_id:
            # Tracearr exposes no Plex machine identifier, so the links Discord shows
            # cannot be built without this being set by hand.
            logger.warning(
                "media_source is 'tracearr', which cannot auto-detect the Plex server id; "
                "set plex_server_id to get clickable media links"
            )
        return TracearrClient(base_url=config.tracearr_url, api_key=config.tracearr_api_key)

    return TautulliClient(
        base_url=config.tautulli_url,
        api_key=config.tautulli_api_key,
        initial_batch_size=config.initial_batch_size,
    )


def _format_display_title(item: MediaItem) -> str:
    """
    Format display title based on media type.

    Args:
        item: Media item dictionary from Tautulli

    Returns:
        Formatted display title string
    """
    media_type = item.get("media_type", "unknown")

    if media_type == "episode":
        show = item.get("grandparent_title", "Unknown Show")
        season_num = item.get("parent_media_index", "?")
        episode_num = item.get("media_index", "?")
        episode_title = item.get("title", "Unknown Episode")
        # Format episode numbers safely, handling non-integer values
        try:
            s_num = int(season_num) if season_num != "?" else 0
            e_num = int(episode_num) if episode_num != "?" else 0
            return f"{show} - S{s_num:02d}E{e_num:02d} - {episode_title}"
        except (ValueError, TypeError):  # fmt: skip
            return f"{show} - S{season_num}E{episode_num} - {episode_title}"
    elif media_type == "season":
        show = item.get("parent_title", "Unknown Show")
        season_num = item.get("media_index", "?")
        return f"{show} - Season {season_num}"
    elif media_type == "show":
        show = str(item.get("title", "Unknown Show"))
        year = item.get("year", "")
        return f"{show} ({year})" if year else f"{show} (New Series)"
    elif media_type == "track":
        artist = item.get("grandparent_title", "Unknown Artist")
        album = item.get("parent_title", "Unknown Album")
        track = item.get("title", "Unknown Track")
        return f"{artist} - {album} - {track}"
    elif media_type == "album":
        artist = item.get("parent_title", "Unknown Artist")
        album = item.get("title", "Unknown Album")
        return f"{artist} - {album}"
    elif media_type == "movie":
        title = str(item.get("title", "Unknown Movie"))
        year = item.get("year", "")
        return f"{title} ({year})" if year else title
    else:
        title = item.get("title", "Unknown")
        return str(title)


def _filter_excluded_media_types(items: list[MediaItem], excluded_media_types: list[str]) -> list[MediaItem]:
    """
    Drop items whose media_type is on the exclusion list.

    Applied before the payload is built so excluded entries never reach the logs,
    the item count, or the notifier — every count the user sees stays consistent.

    Args:
        items: Filtered list of Tautulli media items
        excluded_media_types: Lowercase media types to omit (may be empty)

    Returns:
        The items to keep; the input list unchanged when nothing is excluded
    """
    if not excluded_media_types:
        return items

    excluded = set(excluded_media_types)
    kept: list[MediaItem] = []
    dropped_by_type: dict[str, int] = {}

    for item in items:
        media_type = str(item.get("media_type", "unknown")).lower()
        if media_type in excluded:
            dropped_by_type[media_type] = dropped_by_type.get(media_type, 0) + 1
        else:
            kept.append(item)

    if dropped_by_type:
        dropped_summary = ", ".join(f"{media_type}: {count}" for media_type, count in sorted(dropped_by_type.items()))
        logger.info("Excluded %d item(s) by media type (%s)", len(items) - len(kept), dropped_summary)

    return kept


def _build_discord_payload(items: list[MediaItem]) -> list[DiscordMediaItem]:
    """
    Build the Discord media payload from Tautulli items and log each entry.

    Logs up to DEFAULT_INFO_DISPLAY_LIMIT items per media type at INFO level;
    excess items are counted and reported in a single summary line.

    Args:
        items: Filtered list of Tautulli media items

    Returns:
        List of DiscordMediaItem dicts ready for the notifier
    """
    discord_items: list[DiscordMediaItem] = []
    suppressed_by_type: dict[str, int] = {}
    displayed_by_type: dict[str, int] = {}
    debug_enabled = logger.isEnabledFor(logging.DEBUG)

    for item in items:
        added_at = int(item.get("added_at", 0))
        date_str = datetime.fromtimestamp(added_at, tz=UTC).strftime("%Y-%m-%d %H:%M")
        date_str_short = datetime.fromtimestamp(added_at, tz=UTC).strftime("%Y-%m-%d")
        media_type = item.get("media_type", "unknown")
        display_title = _format_display_title(item)

        if debug_enabled:
            logger.debug("➕ %s | added: %s", display_title, date_str)
        else:
            shown_count = displayed_by_type.get(media_type, 0)
            if shown_count < DEFAULT_INFO_DISPLAY_LIMIT:
                logger.info("➕ %s | added: %s", display_title, date_str)
                displayed_by_type[media_type] = shown_count + 1
            else:
                suppressed_by_type[media_type] = suppressed_by_type.get(media_type, 0) + 1

        discord_item: DiscordMediaItem = {
            "type": media_type,
            "title": display_title,
            "added_at": date_str_short,
        }
        rating_key = item.get("rating_key")
        if rating_key is not None:
            discord_item["rating_key"] = rating_key
        discord_items.append(discord_item)

    if suppressed_by_type:
        suppressed_summary = ", ".join(
            f"{media_type}: {count}" for media_type, count in sorted(suppressed_by_type.items())
        )
        logger.info(
            "... additional items hidden at INFO level by type (%s). "
            "Set log_level: DEBUG in config.yml to see all entries.",
            suppressed_summary,
        )

    return discord_items


def _send_discord_notification(
    config: Config,
    source: MediaSourceClient,
    discord_items: list[DiscordMediaItem],
    days: int,
    total_count: int,
) -> int:
    """
    Auto-detect Plex server ID (if needed) and dispatch the Discord summary.

    Args:
        config: Application configuration
        source: Media source client used for server identity auto-detection
        discord_items: Payload built by _build_discord_payload
        days: Days-back value forwarded to the notifier for display
        total_count: Total item count forwarded to the notifier for display

    Returns:
        0 on success or in scheduled mode (non-fatal errors); 1 on hard failure
        in one-shot mode
    """
    logger.debug("Discord webhook URL configured, sending notification...")
    try:
        plex_server_id = config.plex_server_id

        # Auto-fetch Plex Server ID from Tautulli if not provided
        if not plex_server_id:
            logger.debug("plex_server_id not configured, fetching from Tautulli...")
            try:
                server_info: ServerIdentity = source.get_server_identity()
                plex_server_id = server_info.get("machine_identifier")
                if plex_server_id:
                    logger.info("Auto-detected Plex Server ID: %s", plex_server_id)
                else:
                    logger.warning("Could not auto-detect Plex Server ID from Tautulli")
            except requests.RequestException as e:
                logger.warning("Network error while fetching Plex Server ID: %s", e)
            except (ValueError, RuntimeError) as e:
                logger.warning("Invalid response from Tautulli: %s", e)

        webhook_url = config.discord_webhook_url
        if webhook_url is None:
            raise RuntimeError("discord_webhook_url must not be None — ensure it is set in config.yml")

        notifier = DiscordNotifier(webhook_url, config.plex_url, plex_server_id)
        success = notifier.send_summary(discord_items, days, total_count)
        if not success and config.run_once:
            return 1
    except requests.RequestException as e:
        logger.error("Network error while sending Discord notification: %s", e)
        if config.run_once:
            return 1
    except ValueError as e:
        logger.error("Invalid Discord webhook configuration: %s", e)
        if config.run_once:
            return 1
    except Exception as e:
        logger.exception("Unexpected error while sending Discord notification: %s", e)
        if config.run_once:
            return 1
    return 0


def run_summary(config: Config) -> int:
    """
    Execute the Plex summary task: fetch and display recently added media.

    Args:
        config: Application configuration

    Returns:
        Exit code: 0 for success, 1 for error
    """
    logger.info("🚀 Starting Plex summary (last %d days)", config.days_back)

    source = _build_media_source(config)

    logger.info("Querying recently added items with iterative fetching...")
    try:
        items = source.get_items_added_since(datetime.now(UTC) - timedelta(days=config.days_back))
    except requests.RequestException as e:
        logger.error("Network error while fetching recently added items: %s", e)
        return 1
    except ValueError as e:
        logger.error("Invalid response from Tautulli API: %s", e)
        return 1
    except Exception as e:
        logger.exception("Unexpected error while fetching recently added items: %s", e)
        return 1

    items = _filter_excluded_media_types(items, config.excluded_media_types)

    discord_items = _build_discord_payload(items)

    if config.discord_webhook_url:
        exit_code = _send_discord_notification(config, source, discord_items, config.days_back, len(items))
    else:
        logger.debug("No Discord webhook URL configured, skipping Discord notification")
        exit_code = 0

    logger.info("✅ Run complete: %d items in the last %d days", len(items), config.days_back)
    record_run_completed()
    return exit_code


def main() -> int:
    """
    Main entry point: Choose between scheduled or one-shot execution mode.

    Execution mode is configured via config.yml:
      - set run_once: true to run once and exit
      - or provide cron_schedule to run as a persistent scheduled task
    """
    config_path = _get_config_path()

    # Bootstrap logging level from raw config so load-time logs honor user verbosity
    setup_logging(get_bootstrap_log_level(config_path))

    version = os.getenv("APP_VERSION") or None
    if not version:
        try:
            version = importlib.metadata.version("plex-releases-summary")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"

    version_display = f"v{version}" if re.match(r"^\d+\.\d+\.\d+(?:-.*)?$", version) else version

    print(rf"""
  ─────────────────────────────────
   ____  ____  ____
  |  _ \|  _ \/ ___|
  | |_) | |_) \___ \
  |  __/|  _ < ___) |
  |_|   |_| \_\____/

  Plex Releases Summary  ·  {version_display}
  ─────────────────────────────────
""")
    logger.info("Starting Plex Releases Summary %s", version_display)

    # An install predating a release keeps a config.yml without the newer keys, which
    # would make those settings silently unreachable. Reconcile before loading.
    try:
        sync_missing_config_keys(config_path)
    except Exception as e:  # pragma: no cover - defensive: must never block startup
        logger.warning("Could not reconcile config with the bundled template: %s", e)

    try:
        config = load_config(config_path)
    except Exception as e:
        logger.exception("FATAL: Failed to load configuration: %s", e)
        return 1

    # Now setup logging with config
    setup_logging(config.log_level)

    if config.run_once:
        # One-shot mode: run once and exit
        logger.info("▶️  Starting in ONE-SHOT mode (run_once=true)")
        return run_summary(config)
    else:
        # Scheduled mode: run as daemon with CRON schedule
        logger.info("📅 Starting in SCHEDULED mode")
        # Scheduled mode only: in one-shot mode the process exits before a probe
        # could ever reach it.
        if config.enable_healthcheck:
            try:
                start_health_server(config.health_host, config.health_port)
            except OSError as e:
                logger.error("Could not start health endpoint on %s:%d: %s", config.health_host, config.health_port, e)
                return 1
        # Guaranteed non-None by Pydantic model validator (validate_cron_schedule_required)
        if config.cron_schedule is None:  # pragma: no cover
            raise RuntimeError("cron_schedule must not be None when run_once is False")
        # Wrap run_summary to pass config
        return run_scheduled(lambda: run_summary(config), config.cron_schedule)


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        sys.exit(1)
