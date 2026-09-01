"""Tautulli API client for fetching Plex media library data."""

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, TypedDict, TypeVar, cast

import requests
from pydantic import BaseModel, ConfigDict, ValidationError

from media_source import MediaItem, ServerIdentity

# Type definitions for Tautulli API responses

T = TypeVar("T", bound=BaseModel)

# Tautulli has no server-side date filtering, so batches are widened progressively
# until one reaches past the cutoff. These bound that loop.
MAX_FETCH_ITERATIONS = 50
MAX_FETCH_COUNT = 10000
INTER_BATCH_DELAY_SECONDS = 0.2


class TautulliRecentlyAdded(TypedDict, total=False):
    recently_added: list[MediaItem]


TautulliRecentlyAddedPayload = TautulliRecentlyAdded | list[MediaItem]


# Pydantic models for runtime validation


class TautulliMediaItemModel(BaseModel):
    """Pydantic model for runtime validation of Tautulli media items."""

    model_config = ConfigDict(extra="allow")

    # Required fields
    added_at: int
    media_type: str
    title: str

    # Optional fields
    year: int | str | None = None
    grandparent_title: str | None = None
    parent_title: str | None = None
    parent_media_index: int | str | None = None
    media_index: int | str | None = None
    rating_key: int | str | None = None


class TautulliRecentlyAddedModel(BaseModel):
    """Pydantic model for runtime validation of Tautulli recently_added responses."""

    model_config = ConfigDict(extra="allow")

    recently_added: list[TautulliMediaItemModel]


class TautulliServerIdentityModel(BaseModel):
    """Pydantic model for runtime validation of Tautulli server identity."""

    model_config = ConfigDict(extra="allow")

    machine_identifier: str


logger = logging.getLogger(__name__)


class TautulliClient:
    """Client for interacting with Tautulli API."""

    # Request configuration
    DEFAULT_TIMEOUT = 10  # seconds
    DEFAULT_MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2  # Exponential backoff base (1s, 2s, 4s, ...)
    APIKEY_PATTERN = re.compile(r"(apikey=)[^&\s]+", re.IGNORECASE)

    def __init__(self, base_url: str, api_key: str, initial_batch_size: int | None = None):
        """
        Initialize Tautulli client.

        Args:
            base_url: Base URL of the Tautulli instance
            api_key: Tautulli API key for authentication
            initial_batch_size: Optional override for the fetch batch size
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.initial_batch_size = initial_batch_size

    def _sanitize_error(self, error: Exception) -> str:
        """
        Sanitize exception text to avoid leaking credentials.

        Args:
            error: Exception to sanitize

        Returns:
            Redacted exception message
        """
        message = str(error)
        if self.api_key:
            message = message.replace(self.api_key, "***")
        return self.APIKEY_PATTERN.sub(r"\1***", message)

    def _sanitize_exception(self, error: Exception) -> Exception:
        """
        Create a sanitized exception instance to avoid leaking credentials.

        Args:
            error: Exception to sanitize

        Returns:
            New exception with redacted message
        """
        safe_message = self._sanitize_error(error)
        return type(error)(safe_message)

    def _validate_response(self, data: dict[str, object], model: type[T]) -> T:
        """
        Validate API response data using Pydantic model.

        Args:
            data: Raw response data from API
            model: Pydantic model class to validate against

        Returns:
            Validated model instance

        Raises:
            RuntimeError: If validation fails
        """
        try:
            return model.model_validate(data)
        except ValidationError as e:
            # Extract a concise error message
            errors = e.errors()
            error_details = "; ".join(
                [
                    f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" if err["loc"] else err["msg"]
                    for err in errors
                ]
            )
            sanitized_msg = self._sanitize_error(Exception(error_details))
            raise RuntimeError(f"Tautulli response validation failed: {sanitized_msg}") from None

    def _request(self, cmd: str, max_retries: int | None = None, **params: Any) -> dict[str, object] | list[object]:
        """
        Make a request to Tautulli API with exponential backoff retry logic.

        Args:
            cmd: Tautulli API command to execute
            max_retries: Maximum number of retry attempts (default: DEFAULT_MAX_RETRIES)
            **params: Additional query parameters for the API request

        Returns:
            Dict or list containing the API response data (list form occurs in older
            Tautulli API versions where ``response['data']`` is returned as a bare list)

        Raises:
            requests.RequestException: If request fails after all retries
            RuntimeError: If Tautulli returns unsuccessful response
        """
        if max_retries is None:
            max_retries = self.DEFAULT_MAX_RETRIES

        url = f"{self.base_url}/api/v2"
        query = {
            "apikey": self.api_key,
            "cmd": cmd,
            **params,
        }
        logger.debug("Requesting Tautulli: %s", cmd)

        last_exception: Exception = RuntimeError("No attempts made")
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, params=query, timeout=self.DEFAULT_TIMEOUT)
                resp.raise_for_status()

                data = cast(dict[str, object], resp.json())
                response = cast(dict[str, object], data.get("response", {}))
                if response.get("result") != "success":
                    message = response.get("message", "unknown error")
                    raise RuntimeError(f"Tautulli command '{cmd}' returned unsuccessful response: {message}")
                response_payload = cast(dict[str, object] | list[object], response.get("data", {}))
                return response_payload

            except (requests.RequestException, RuntimeError) as e:
                last_exception = e
                safe_error = self._sanitize_error(e)
                if attempt < max_retries - 1:
                    wait_time = self.RETRY_BACKOFF_BASE**attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(
                        "Request failed for cmd=%s (attempt %d/%d): %s. Retrying in %ds...",
                        cmd,
                        attempt + 1,
                        max_retries,
                        safe_error,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("Request failed for cmd=%s after %d attempts: %s", cmd, max_retries, safe_error)

        raise self._sanitize_exception(last_exception) from None

    def get_recently_added(self, days: int = 7, count: int = 100) -> TautulliRecentlyAddedPayload:
        """
        Get recently added items from Tautulli.

        Note: The Tautulli API doesn't support date filtering natively, so this method
        retrieves a batch of items and the caller must filter them client-side by timestamp.

        Args:
            days: Number of days to look back. Used only for debug logging; the actual
                date filtering is performed by the caller against each item's timestamp.
                This value is NOT forwarded to the Tautulli API.
            count: Maximum number of items to retrieve from API

        Returns:
            Dict containing Tautulli API response with 'recently_added' list of media items
        """
        logger.debug("Requesting %d recently added items (will filter to last %d days client-side)", count, days)

        response_payload = self._request(
            "get_recently_added",
            count=count,
        )

        # Validate response - handle both dict and list formats
        # Try dict format first (newer API)
        if isinstance(response_payload, dict) and "recently_added" in response_payload:
            validated = self._validate_response(response_payload, TautulliRecentlyAddedModel)
            return cast(TautulliRecentlyAddedPayload, validated.model_dump())
        elif isinstance(response_payload, list):
            # List format (older API)
            validated_items = [
                self._validate_response(cast(dict[str, object], item), TautulliMediaItemModel)
                for item in response_payload
            ]
            return cast(TautulliRecentlyAddedPayload, [item.model_dump() for item in validated_items])
        else:
            raise RuntimeError(f"Unexpected response format: {type(response_payload).__name__}")

    def get_server_identity(self) -> ServerIdentity:
        """
        Get Plex server identity information including machine identifier.

        Returns:
            Dict with server info including 'machine_identifier'
        """
        logger.debug("Requesting Plex server identity")
        response_payload = self._request("get_server_identity")
        if not isinstance(response_payload, dict):
            raise RuntimeError(
                f"Unexpected response format for get_server_identity: expected dict, got {type(response_payload).__name__}"
            )
        validated = self._validate_response(response_payload, TautulliServerIdentityModel)
        return cast(ServerIdentity, validated.model_dump())

    @staticmethod
    def _calculate_batch_params(days: int, override: int | None = None) -> tuple[int, int]:
        """
        Calculate initial batch size and increment based on time range.

        Args:
            days: Number of days to look back
            override: Optional override value from configuration

        Returns:
            Tuple of (initial_count, increment)
        """
        if override is not None:
            return (override, override)

        if days <= 7:
            return (100, 100)
        elif days <= 30:
            return (200, 200)
        else:
            return (500, 500)

    def get_items_added_since(self, cutoff: datetime) -> list[MediaItem]:
        """
        Fetch every item added at or after ``cutoff``, newest first.

        Tautulli has no server-side date filtering, so batches are widened
        progressively until one reaches past the cutoff, then filtered client-side.
        Pagination lives here rather than in the caller because each media source
        pages its own way.

        Args:
            cutoff: Oldest moment to include

        Returns:
            List of media items added within the window

        Raises:
            requests.RequestException: On network failures
            ValueError: On invalid API responses
            RuntimeError: On unexpected Tautulli errors
        """
        cutoff_timestamp = int(cutoff.timestamp())
        days = max(1, (datetime.now(UTC) - cutoff).days)
        logger.debug("Filtering items to show only those added after timestamp: %d", cutoff_timestamp)

        initial_count, increment = self._calculate_batch_params(days, override=self.initial_batch_size)
        current_count = initial_count
        iteration = 0
        items: list[MediaItem] = []

        while True:
            iteration += 1

            if iteration > MAX_FETCH_ITERATIONS:
                logger.warning(
                    "Reached max fetch iterations (%d); proceeding with latest batch and date filtering",
                    MAX_FETCH_ITERATIONS,
                )
                break

            logger.debug("Iteration %d: Fetching batch with count=%d", iteration, current_count)

            # Small delay between iterations to avoid hammering the API
            if iteration > 1:
                time.sleep(INTER_BATCH_DELAY_SECONDS)

            items_raw: TautulliRecentlyAddedPayload = self.get_recently_added(days=days, count=current_count)

            # Handle both dict (newer API) and list (older API) response formats
            if isinstance(items_raw, dict) and "recently_added" in items_raw:
                items = items_raw["recently_added"]
            elif isinstance(items_raw, list):
                items = items_raw
            else:
                items = []

            if not items:
                logger.debug("No items returned, stopping iteration")
                break

            # If we received fewer items than requested, we've hit the API's limit
            if len(items) < current_count:
                logger.debug("Received %d items (less than requested %d), reached API limit", len(items), current_count)
                break

            oldest_timestamp = int(items[-1].get("added_at", 0))

            if oldest_timestamp >= cutoff_timestamp:
                # Oldest item is still in range - expand the batch
                next_count = current_count + increment
                if next_count > MAX_FETCH_COUNT:
                    logger.warning(
                        "Reached max fetch count limit (%d); proceeding with current results",
                        MAX_FETCH_COUNT,
                    )
                    break
                logger.debug(
                    "Oldest item still in range (iteration %d), fetching more items (next count: %d)",
                    iteration,
                    next_count,
                )
                current_count = next_count
            else:
                # Oldest item is outside the range - we have everything we need
                logger.debug("Fetched beyond time range after %d iteration(s)", iteration)
                break

        # Client-side date filter
        items_before_filter = len(items)
        items = [item for item in items if int(item.get("added_at", 0)) >= cutoff_timestamp]

        if iteration > 1:
            logger.info(
                "Retrieved %d items in %d iterations, filtered to %d items from last %d days",
                items_before_filter,
                iteration,
                len(items),
                days,
            )
        else:
            logger.info(
                "Retrieved %d items, filtered to %d items from last %d days",
                items_before_filter,
                len(items),
                days,
            )

        return items
