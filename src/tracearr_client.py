"""Tracearr API client, an alternative media source to Tautulli.

Two things make this more than a thin HTTP wrapper:

- **Grouping.** Tautulli relays Plex's *recently added* hub, which collapses bulk
  additions into one entry per show or season. Tracearr exposes its raw table, so the
  same week is 213 rows where Tautulli reports 17. Rows are therefore clustered here
  into the same shape before the summary sees them.
- **Enrichment.** ``/recently-added`` returns rating keys but not the show title,
  season number or episode number that the summary renders, even though Tracearr
  stores them. They are recovered by walking its media tree.
"""

import logging
import re
import time
from datetime import datetime
from typing import Any, TypeVar, cast

import requests
from pydantic import BaseModel, ConfigDict, ValidationError

from media_source import MediaItem, ServerIdentity

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

API_PREFIX = "/api/v2/public"
# Tracearr caps pageSize at 100 (cursorPaginationSchema); asking for more is a 400.
PAGE_SIZE = 100
MAX_PAGES = 50
MAX_SEND_RETRIES = 3
RETRY_BACKOFF_BASE = 2
REQUEST_TIMEOUT_SECONDS = 15

# Episodes added within this gap of each other count as one burst. Measured against a
# real library: genuine bulk imports keep consecutive additions within ~6 minutes,
# while a weekly episode drop sits ~40 hours from its neighbour. Anything in between
# separates the two cases, so this is deliberately generous.
BURST_GAP_SECONDS = 3600


class TracearrLibraryItem(BaseModel):
    """A row from /recently-added, validated loosely: unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    media_type: str
    title: str
    added_at: str
    server_type: str | None = None
    year: int | None = None
    media_id: str | None = None
    rating_key: str | None = None
    parent_rating_key: str | None = None
    grandparent_rating_key: str | None = None


class TracearrClient:
    """Reads recently added media from a Tracearr instance's public API."""

    def __init__(self, base_url: str, api_key: str, server_id: str | None = None):
        """
        Initialize the Tracearr client.

        Args:
            base_url: Base URL of the Tracearr instance
            api_key: Public API token (trr_pub_...)
            server_id: Optional media server id, to scope a multi-server instance
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.server_id = server_id
        # Enrichment caches, keyed by media id. Scoped to the client instance so a
        # scheduled run starts fresh rather than serving a stale library shape.
        self._show_cache: dict[str, dict[str, Any]] = {}
        self._season_cache: dict[str, list[dict[str, Any]]] = {}
        self._episode_index: dict[str, tuple[int | None, int | None]] = {}
        # Plex rating key -> Tracearr media uuid, harvested from the show and season
        # rows the feed already returns alongside episodes. Saves a lookup per entry.
        self._media_id_by_key: dict[str, str] = {}
        self._request_count = 0

    def _sanitize_error(self, error: Exception) -> str:
        """
        Sanitize exception text so the API token never reaches a log.

        Args:
            error: Exception to sanitize

        Returns:
            Redacted exception message
        """
        message = str(error)
        if self.api_key:
            message = message.replace(self.api_key, "***")
        return re.sub(r"trr_pub_[A-Za-z0-9_-]+", "trr_pub_***", message)

    def _sanitize_exception(self, error: Exception) -> Exception:
        """Rebuild an exception with its message redacted."""
        return type(error)(self._sanitize_error(error))

    def _validate_response(self, data: dict[str, object], model: type[T]) -> T:
        """
        Validate a payload against a pydantic model.

        Args:
            data: Raw payload
            model: Model to validate against

        Returns:
            The validated model

        Raises:
            ValueError: If validation fails
        """
        try:
            return model.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"Unexpected Tracearr response shape: {e.error_count()} field error(s)") from None

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Perform an authenticated GET with retry and backoff.

        Args:
            path: Path below the public API prefix, e.g. "/recently-added"
            params: Optional query parameters

        Returns:
            Decoded JSON object

        Raises:
            requests.RequestException: On network failures after all retries
            ValueError: If the response is not a JSON object
        """
        url = f"{self.base_url}{API_PREFIX}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_exception: Exception = RuntimeError("No attempts made")

        for attempt in range(MAX_SEND_RETRIES):
            try:
                self._request_count += 1
                response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected a JSON object from {path}")
                return cast(dict[str, Any], payload)
            except requests.RequestException as e:
                last_exception = e
                safe_error = self._sanitize_error(e)
                if attempt < MAX_SEND_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_BASE**attempt
                    logger.warning(
                        "Request failed for %s (attempt %d/%d): %s. Retrying in %ds...",
                        path,
                        attempt + 1,
                        MAX_SEND_RETRIES,
                        safe_error,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("Request failed for %s after %d attempts: %s", path, MAX_SEND_RETRIES, safe_error)

        raise self._sanitize_exception(last_exception) from None

    def get_server_identity(self) -> ServerIdentity:
        """
        Return the backing server's identity.

        Always empty: Tracearr records the Plex ``machineIdentifier`` but exposes it
        only on its internal authenticated API, not the public surface. Deep links
        therefore need ``media_server_id`` to be configured explicitly.
        """
        logger.debug("Tracearr does not expose the Plex machine identifier; skipping auto-detection")
        return {}

    # ---------------------------------------------------------------- fetching

    def _iter_recent_rows(self, cutoff: datetime) -> list[TracearrLibraryItem]:
        """
        Page /recently-added until the feed reaches past the cutoff.

        The feed is ordered newest first with a keyset cursor, so the first row older
        than the cutoff ends the walk.

        Args:
            cutoff: Oldest moment to include

        Returns:
            Validated rows added at or after the cutoff
        """
        rows: list[TracearrLibraryItem] = []
        cursor: str | None = None

        for _page in range(MAX_PAGES):
            params: dict[str, Any] = {"pageSize": PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            if self.server_id:
                params["server_id"] = self.server_id

            payload = self._request("/recently-added", params)
            data = payload.get("data") or []
            if not isinstance(data, list):
                raise ValueError("Expected 'data' to be a list in the /recently-added payload")

            reached_cutoff = False
            for raw in data:
                item = self._validate_response(cast(dict[str, object], raw), TracearrLibraryItem)
                if _parse_iso(item.added_at) < cutoff:
                    reached_cutoff = True
                    break
                rows.append(item)

            cursor = (payload.get("meta") or {}).get("nextCursor")
            if reached_cutoff or not cursor or not data:
                break
        else:
            logger.warning("Reached max pages (%d) walking /recently-added; using what was collected", MAX_PAGES)

        logger.debug("Collected %d raw rows from Tracearr within the window", len(rows))
        return rows

    def get_items_added_since(self, cutoff: datetime) -> list[MediaItem]:
        """
        Fetch every item added at or after ``cutoff``, grouped and enriched.

        Args:
            cutoff: Oldest moment to include

        Returns:
            Media items in the shape the summary renders, newest first

        Raises:
            requests.RequestException: On network failures
            ValueError: On invalid API responses
        """
        self._request_count = 0
        rows = self._iter_recent_rows(cutoff)

        episodes = [r for r in rows if r.media_type == "episode"]
        self._index_media_ids(rows)

        # A bulk import shows up in Tracearr as the episodes *and* their season and
        # show rows. Plex reports one entry for the lot, so the rows already covered
        # by a grouped episode burst are dropped rather than counted twice.
        covered_shows = {r.grandparent_rating_key for r in episodes if r.grandparent_rating_key}
        covered_seasons = {r.parent_rating_key for r in episodes if r.parent_rating_key}

        items: list[MediaItem] = []
        for row in rows:
            if row.media_type == "episode":
                continue
            if row.media_type == "show" and row.rating_key in covered_shows:
                continue
            if row.media_type == "season" and row.rating_key in covered_seasons:
                continue
            items.append(self._passthrough_entry(row))

        items.extend(self._group_episodes(episodes))

        # Newest first, matching the order the summary expects.
        items.sort(key=lambda i: int(i.get("added_at", 0)), reverse=True)

        logger.info(
            "Retrieved %d raw rows, grouped to %d entries from last %d days (%d API calls)",
            len(rows),
            len(items),
            max(1, (datetime.now(cutoff.tzinfo) - cutoff).days),
            self._request_count,
        )
        return items

    # ---------------------------------------------------------------- grouping

    def _group_episodes(self, episodes: list[TracearrLibraryItem]) -> list[MediaItem]:
        """
        Collapse episode rows the way Plex's recently-added hub does.

        Episodes of one show that arrived in the same burst are one entry: a show entry
        if the burst spans several seasons, a season entry if it stays within one. An
        episode that arrived on its own stays an episode, which is what keeps a weekly
        drop visible instead of being folded into its season.

        Note that a burst straddling the days_back cutoff is only partly visible here,
        since rows age out individually — unlike Plex's grouped entry, which is atomic.
        The remainder therefore regroups on what is left, which can differ from what
        Tautulli reports for the same moment. See CONFIGURATION.md#choosing-a-media-source.

        Args:
            episodes: Episode rows within the window

        Returns:
            Grouped and enriched media items
        """
        by_show: dict[str, list[TracearrLibraryItem]] = {}
        for episode in episodes:
            key = episode.grandparent_rating_key or f"__unknown__{episode.rating_key}"
            by_show.setdefault(key, []).append(episode)

        grouped: list[MediaItem] = []
        for show_episodes in by_show.values():
            show_episodes.sort(key=lambda e: _parse_iso(e.added_at))
            for burst in _split_into_bursts(show_episodes):
                grouped.append(self._entry_for_burst(burst))
        return grouped

    def _entry_for_burst(self, burst: list[TracearrLibraryItem]) -> MediaItem:
        """
        Decide what a single burst of episodes should be rendered as.

        Args:
            burst: Episodes of one show added together

        Returns:
            One media item representing the burst
        """
        newest = max(burst, key=lambda e: _parse_iso(e.added_at))
        seasons_touched = {e.parent_rating_key for e in burst if e.parent_rating_key}

        if len(seasons_touched) > 1:
            return self._as_show_entry(newest)
        if len(burst) > 1:
            return self._as_season_entry(newest)
        return self._as_episode_entry(newest)

    # -------------------------------------------------------------- enrichment

    def _to_media_item(self, row: TracearrLibraryItem) -> MediaItem:
        """Translate a row into the summary's shape, without any extra lookups."""
        item: MediaItem = {
            "media_type": row.media_type,
            "title": row.title,
            "added_at": int(_parse_iso(row.added_at).timestamp()),
        }
        if row.server_type:
            item["server_type"] = row.server_type
        if row.year is not None:
            item["year"] = row.year
        if row.rating_key:
            item["rating_key"] = row.rating_key
        return item

    def _index_media_ids(self, rows: list[TracearrLibraryItem]) -> None:
        """Remember the media uuid behind each show and season rating key in the feed."""
        for row in rows:
            if row.media_type in ("show", "season") and row.rating_key and row.media_id:
                self._media_id_by_key[row.rating_key] = row.media_id

    def _passthrough_entry(self, row: TracearrLibraryItem) -> MediaItem:
        """
        Render a row that needs no grouping: a movie, or a show or season with no
        episodes of its own inside the window.
        """
        if row.media_type == "season":
            return self._season_item(
                added_at=row.added_at,
                season_media_id=row.media_id,
                show_key=row.parent_rating_key,
                season_key=row.rating_key,
                fallback_title=row.title,
                server_type=row.server_type,
            )
        return self._to_media_item(row)

    def _show_by_media_id(self, media_id: str) -> dict[str, Any]:
        """Fetch a show's canonical record, cached per media id."""
        if media_id not in self._show_cache:
            self._show_cache[media_id] = self._request(f"/media/{media_id}")
        return self._show_cache[media_id]

    def _show_for_key(self, show_key: str | None) -> dict[str, Any]:
        """
        Resolve a show from its Plex rating key, when the feed told us its media id.

        Args:
            show_key: Plex rating key of the show

        Returns:
            The show's record, empty if unknown or unreachable
        """
        media_id = self._media_id_by_key.get(show_key or "")
        if not media_id:
            return {}
        try:
            return self._show_by_media_id(media_id)
        except (requests.RequestException, ValueError) as e:
            logger.debug("Could not resolve show %s: %s", show_key, self._sanitize_error(e))
            return {}

    def _season_number_for(self, show: dict[str, Any], season_media_id: str | None) -> int | None:
        """
        Look up a season's number by matching its media id among the show's children.

        Cheaper and more direct than searching episodes, and it works for a season row
        that has no episodes inside the window.
        """
        show_id = show.get("id")
        if not show_id or not season_media_id:
            return None
        try:
            if show_id not in self._season_cache:
                payload = self._request(f"/media/{show_id}/children")
                self._season_cache[show_id] = payload.get("data") or []
            for season in self._season_cache[show_id]:
                if season.get("id") == season_media_id:
                    number = season.get("season_number")
                    return int(number) if number is not None else None
        except (requests.RequestException, ValueError) as e:
            logger.debug("Could not resolve season number: %s", self._sanitize_error(e))
        return None

    def _season_item(
        self,
        added_at: str,
        season_media_id: str | None,
        show_key: str | None,
        season_key: str | None,
        fallback_title: str,
        server_type: str | None = None,
        fallback_episode: TracearrLibraryItem | None = None,
    ) -> MediaItem:
        """
        Build a season entry, resolving the show title and season number.

        The rating-key map only knows shows whose own row is inside the window. A show
        added long ago that just gained a few episodes is not in it, so an episode of
        the season is used to climb to the show instead.
        """
        show = self._show_for_key(show_key)
        if not show and fallback_episode is not None:
            show = self._show_details(fallback_episode)

        season_number = self._season_number_for(show, season_media_id)
        if season_number is None and fallback_episode is not None:
            season_number, _ = self._locate_episode(fallback_episode, show)
        item: MediaItem = {
            "media_type": "season",
            "title": show.get("title") or fallback_title,
            "parent_title": show.get("title") or "Unknown Show",
            "added_at": int(_parse_iso(added_at).timestamp()),
        }
        if server_type:
            item["server_type"] = server_type
        if season_number is not None:
            item["media_index"] = season_number
        if season_key:
            item["rating_key"] = season_key
        return item

    def _show_details(self, episode: TracearrLibraryItem) -> dict[str, Any]:
        """
        Resolve the show behind an episode: its media id, title and year.

        Args:
            episode: An episode row

        Returns:
            The show's details, empty if it could not be resolved
        """
        if not episode.media_id:
            return {}

        try:
            episode_media = self._request(f"/media/{episode.media_id}")
            show_id = episode_media.get("show_media_id")
            if not show_id:
                return {}
            if show_id not in self._show_cache:
                self._show_cache[show_id] = self._request(f"/media/{show_id}")
            return self._show_cache[show_id]
        except (requests.RequestException, ValueError) as e:
            # Non-fatal by design: a plain title beats a failed run.
            logger.debug("Could not resolve the show for %r: %s", episode.title, self._sanitize_error(e))
            return {}

    def _locate_episode(self, episode: TracearrLibraryItem, show: dict[str, Any]) -> tuple[int | None, int | None]:
        """
        Find an episode's season and episode numbers by walking the show's children.

        A season's children carry no rating key, so the episode cannot be matched by
        ``parent_rating_key`` — the seasons are searched by episode media id instead.
        Newest seasons first, since recent additions cluster there.

        Args:
            episode: The episode to locate
            show: The show details from _show_details

        Returns:
            (season_number, episode_number), either may be None if not found
        """
        show_id = show.get("id")
        if not show_id or not episode.media_id:
            return (None, None)

        if episode.media_id in self._episode_index:
            return self._episode_index[episode.media_id]

        try:
            if show_id not in self._season_cache:
                payload = self._request(f"/media/{show_id}/children")
                seasons = payload.get("data") or []
                self._season_cache[show_id] = sorted(seasons, key=lambda s: s.get("season_number") or 0, reverse=True)

            for season in self._season_cache[show_id]:
                season_id = season.get("id")
                if not season_id:
                    continue
                payload = self._request(f"/media/{season_id}/children")
                for child in payload.get("data") or []:
                    self._episode_index[child.get("id")] = (
                        season.get("season_number"),
                        child.get("episode_number"),
                    )
                if episode.media_id in self._episode_index:
                    return self._episode_index[episode.media_id]
        except (requests.RequestException, ValueError) as e:
            logger.debug("Could not locate episode %r in its show: %s", episode.title, self._sanitize_error(e))

        return (None, None)

    def _as_show_entry(self, episode: TracearrLibraryItem) -> MediaItem:
        """Render a multi-season burst as a show entry, as Plex would."""
        show = self._show_for_key(episode.grandparent_rating_key) or self._show_details(episode)
        item: MediaItem = {
            "media_type": "show",
            "title": show.get("title") or episode.title,
            "added_at": int(_parse_iso(episode.added_at).timestamp()),
        }
        if episode.server_type:
            item["server_type"] = episode.server_type
        if show.get("year") is not None:
            item["year"] = show["year"]
        # Always set: a show entry only arises from a burst spanning several seasons,
        # which requires the episodes to share a grandparent rating key.
        item["rating_key"] = episode.grandparent_rating_key or ""
        return item

    def _as_season_entry(self, episode: TracearrLibraryItem) -> MediaItem:
        """Render a single-season burst as a season entry."""
        return self._season_item(
            added_at=episode.added_at,
            season_media_id=self._media_id_by_key.get(episode.parent_rating_key or ""),
            show_key=episode.grandparent_rating_key,
            season_key=episode.parent_rating_key,
            fallback_title=episode.title,
            server_type=episode.server_type,
            fallback_episode=episode,
        )

    def _as_episode_entry(self, episode: TracearrLibraryItem) -> MediaItem:
        """Render a lone episode, resolving its show title and numbering."""
        show = self._show_for_key(episode.grandparent_rating_key) or self._show_details(episode)
        season_number, episode_number = self._locate_episode(episode, show)
        item: MediaItem = self._to_media_item(episode)
        if show.get("title"):
            item["grandparent_title"] = show["title"]
        if season_number is not None:
            item["parent_media_index"] = season_number
        if episode_number is not None:
            item["media_index"] = episode_number
        return item


def _parse_iso(value: str) -> datetime:
    """
    Parse an ISO 8601 timestamp from Tracearr, which uses a trailing Z.

    Args:
        value: Timestamp string

    Returns:
        Timezone-aware datetime

    Raises:
        ValueError: If the value cannot be parsed
    """
    # fromisoformat handles a trailing Z natively on 3.11+.
    return datetime.fromisoformat(value)


def _split_into_bursts(episodes: list[TracearrLibraryItem]) -> list[list[TracearrLibraryItem]]:
    """
    Split chronologically sorted episodes wherever the gap exceeds BURST_GAP_SECONDS.

    Args:
        episodes: Episodes of one show, oldest first

    Returns:
        One list per burst
    """
    bursts: list[list[TracearrLibraryItem]] = []
    for episode in episodes:
        if (
            bursts
            and (_parse_iso(episode.added_at) - _parse_iso(bursts[-1][-1].added_at)).total_seconds()
            <= BURST_GAP_SECONDS
        ):
            bursts[-1].append(episode)
        else:
            bursts.append([episode])
    return bursts
