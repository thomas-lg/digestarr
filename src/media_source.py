"""Backend-neutral contract for a source of recently added media.

Tautulli is one implementation; anything able to answer "what was added since this
moment" can be another. The item shape is deliberately the one the summary needs, so
a backend is responsible for translating its own payloads into it.
"""

from datetime import datetime
from typing import Protocol, TypedDict


class MediaItem(TypedDict, total=False):
    """A single recently added library entry, as the summary consumes it."""

    added_at: int | str
    grandparent_title: str
    media_index: int | str
    media_type: str
    parent_media_index: int | str
    parent_title: str
    rating_key: int | str
    # Which media server the item lives on: "plex", "jellyfin" or "emby". Decides the
    # shape of the deep link; absent means Plex, which is all a Plex-only source such
    # as Tautulli can ever report.
    server_type: str
    title: str
    year: int | str


class ServerIdentity(TypedDict, total=False):
    """Identity of the media server behind the source, used for deep links."""

    machine_identifier: str


class MediaSourceClient(Protocol):
    """
    Structural interface for a media source, enabling test stubs without subclassing.

    Pagination is the implementation's concern: each backend pages its own way, so the
    contract asks for a time window rather than a batch size.
    """

    def get_items_added_since(self, cutoff: datetime) -> list[MediaItem]:
        """Return every item added at or after ``cutoff``, newest first."""
        ...  # pragma: no cover

    def get_server_identity(self) -> ServerIdentity:
        """Return the backing server's identity, empty if unavailable."""
        ...  # pragma: no cover
