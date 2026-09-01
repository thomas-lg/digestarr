"""Unit tests for the Tracearr media source.

Payload shapes are taken from a live Tracearr instance, so these are pinned to what
the API actually returns rather than to a reading of its source.
"""

from datetime import UTC, datetime, timedelta

import pytest
import requests

from src.tracearr_client import BURST_GAP_SECONDS, PAGE_SIZE, TracearrClient

SHOW_ID = "ec84c5ac-5fad-4656-b9c5-cad53644b1bb"
SEASON1_ID = "01ce04c1-b580-4e2c-bd2b-64480085d568"
SEASON2_ID = "29fffdfb-20a0-416a-bf08-807a760f4d52"


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _episode(rating_key, media_id, added, season_key="2982", show_key="2947", title="Un episode"):
    return {
        "media_type": "episode",
        "title": title,
        "year": 2023,
        "added_at": _iso(added),
        "media_id": media_id,
        "rating_key": rating_key,
        "parent_rating_key": season_key,
        "grandparent_rating_key": show_key,
    }


class FakeTransport:
    """Serves canned Tracearr responses and records what was asked for."""

    def __init__(self, pages, media=None, children=None, fail_paths=()):
        self.pages = pages
        self.media = media or {}
        self.children = children or {}
        self.fail_paths = set(fail_paths)
        self.calls = []
        self.headers_seen = []
        self.params_seen = []

    def __call__(self, url, headers=None, params=None, timeout=None):
        path = url.split("/api/v2/public", 1)[1]
        self.calls.append(path)
        self.headers_seen.append(headers or {})
        self.params_seen.append(params or {})

        if path in self.fail_paths:
            raise requests.RequestException(f"boom for {path}")

        if path == "/recently-added":
            cursor = (params or {}).get("cursor")
            index = 0 if cursor is None else int(cursor)
            return _Response(self.pages[index])
        if path.endswith("/children"):
            return _Response({"data": self.children.get(path.split("/")[2], [])})
        return _Response(self.media.get(path.split("/")[2], {}))


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client(transport, monkeypatch, **kwargs):
    monkeypatch.setattr("src.tracearr_client.requests.get", transport)
    monkeypatch.setattr("src.tracearr_client.time.sleep", lambda _s: None)
    return TracearrClient("http://tracearr:3000", "trr_pub_secret", **kwargs)


def _cutoff(days=7):
    return datetime.now(UTC) - timedelta(days=days)


class TestRequestBasics:
    """Authentication, paging limits and error handling."""

    @pytest.mark.unit
    def test_sends_bearer_token_and_capped_page_size(self, monkeypatch):
        """The token travels as a bearer header, and pageSize respects Tracearr's cap of 100."""
        transport = FakeTransport([{"data": [], "meta": {}}])
        client = _client(transport, monkeypatch)

        client.get_items_added_since(_cutoff())

        assert transport.headers_seen[0]["Authorization"] == "Bearer trr_pub_secret"
        assert transport.params_seen[0]["pageSize"] == PAGE_SIZE
        assert PAGE_SIZE <= 100

    @pytest.mark.unit
    def test_server_identity_is_empty(self, monkeypatch):
        """Tracearr cannot report the Plex machine identifier, so links need config."""
        client = _client(FakeTransport([{"data": [], "meta": {}}]), monkeypatch)

        assert client.get_server_identity() == {}

    @pytest.mark.unit
    def test_api_token_never_appears_in_a_sanitized_error(self, monkeypatch):
        """A leaked token in a log would outlive the run; it must be redacted."""
        client = _client(FakeTransport([{"data": [], "meta": {}}]), monkeypatch)
        error = RuntimeError("401 for http://tracearr:3000?token=trr_pub_secret")

        message = client._sanitize_error(error)

        assert "trr_pub_secret" not in message
        assert "***" in message

    @pytest.mark.unit
    def test_network_failure_propagates_after_retries(self, monkeypatch):
        """The caller decides what a dead source means, so the error is re-raised."""
        transport = FakeTransport([{"data": [], "meta": {}}], fail_paths=["/recently-added"])
        client = _client(transport, monkeypatch)

        with pytest.raises(requests.RequestException):
            client.get_items_added_since(_cutoff())

        assert transport.calls.count("/recently-added") == 3


class TestPaging:
    """Walking the cursor-paginated feed."""

    @pytest.mark.unit
    def test_stops_at_the_first_row_older_than_the_cutoff(self, monkeypatch):
        """The feed is newest-first, so one old row ends the walk."""
        now = datetime.now(UTC)
        pages = [
            {
                "data": [
                    {"media_type": "movie", "title": "Recent", "added_at": _iso(now), "rating_key": "1"},
                    {
                        "media_type": "movie",
                        "title": "Ancient",
                        "added_at": _iso(now - timedelta(days=40)),
                        "rating_key": "2",
                    },
                ],
                "meta": {"nextCursor": "1"},
            },
            {"data": [], "meta": {}},
        ]
        transport = FakeTransport(pages)
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert [i["title"] for i in items] == ["Recent"]
        assert transport.calls.count("/recently-added") == 1

    @pytest.mark.unit
    def test_follows_the_cursor_across_pages(self, monkeypatch):
        """A full page in range must be followed by its successor."""
        now = datetime.now(UTC)
        pages = [
            {
                "data": [{"media_type": "movie", "title": "A", "added_at": _iso(now), "rating_key": "1"}],
                "meta": {"nextCursor": "1"},
            },
            {
                "data": [{"media_type": "movie", "title": "B", "added_at": _iso(now), "rating_key": "2"}],
                "meta": {},
            },
        ]
        transport = FakeTransport(pages)
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert sorted(i["title"] for i in items) == ["A", "B"]
        assert transport.params_seen[1]["cursor"] == "1"


class TestGrouping:
    """Collapsing raw rows the way Plex's recently-added hub does."""

    @staticmethod
    def _tree():
        media = {
            SHOW_ID: {"id": SHOW_ID, "media_type": "show", "title": "Vinland Saga", "year": 2019},
            "ep-a": {"id": "ep-a", "media_type": "episode", "show_media_id": SHOW_ID},
        }
        children = {
            SHOW_ID: [
                {"id": SEASON1_ID, "media_type": "season", "season_number": 1},
                {"id": SEASON2_ID, "media_type": "season", "season_number": 2},
            ],
            SEASON2_ID: [{"id": "ep-a", "media_type": "episode", "episode_number": 24}],
            SEASON1_ID: [],
        }
        return media, children

    @pytest.mark.unit
    def test_burst_spanning_two_seasons_becomes_a_show_entry(self, monkeypatch):
        """A bulk import touching several seasons is one show line, as Plex reports it."""
        now = datetime.now(UTC)
        media, children = self._tree()
        rows = [
            _episode("1", "ep-a", now, season_key=SEASON2_ID),
            _episode("2", "ep-b", now - timedelta(minutes=5), season_key="other-season"),
        ]
        # The show row is in the feed too, so the rating key maps straight to a media id.
        rows.append(
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "year": 2019,
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            }
        )
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 1
        assert items[0]["media_type"] == "show"
        assert items[0]["title"] == "Vinland Saga"

    @pytest.mark.unit
    def test_burst_within_one_season_becomes_a_season_entry(self, monkeypatch):
        """Several episodes of one season arriving together collapse into the season."""
        now = datetime.now(UTC)
        media, children = self._tree()
        rows = [
            _episode("1", "ep-a", now, season_key=SEASON2_ID),
            _episode("2", "ep-b", now - timedelta(minutes=5), season_key=SEASON2_ID),
            {
                "media_type": "season",
                "title": "Saison 2",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "rating_key": SEASON2_ID,
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "year": 2019,
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 1
        assert items[0]["media_type"] == "season"
        assert items[0]["parent_title"] == "Vinland Saga"
        assert items[0]["media_index"] == 2

    @pytest.mark.unit
    def test_a_lone_episode_stays_an_episode(self, monkeypatch):
        """The weekly drop is the interesting entry; it must not be folded into a season."""
        now = datetime.now(UTC)
        media, children = self._tree()
        rows = [_episode("1", "ep-a", now, season_key=SEASON2_ID, title="Retour au pays")]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 1
        assert items[0]["media_type"] == "episode"
        assert items[0]["grandparent_title"] == "Vinland Saga"
        assert items[0]["parent_media_index"] == 2
        assert items[0]["media_index"] == 24

    @pytest.mark.unit
    def test_episodes_far_apart_are_separate_bursts(self, monkeypatch):
        """Two weekly episodes of one season are two entries, not a collapsed season."""
        now = datetime.now(UTC)
        media, children = self._tree()
        rows = [
            _episode("1", "ep-a", now, season_key=SEASON2_ID),
            _episode("2", "ep-b", now - timedelta(seconds=BURST_GAP_SECONDS * 2), season_key=SEASON2_ID),
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 2
        assert {i["media_type"] for i in items} == {"episode"}

    @pytest.mark.unit
    def test_movies_pass_straight_through(self, monkeypatch):
        """Movies need no grouping and no lookups."""
        now = datetime.now(UTC)
        rows = [{"media_type": "movie", "title": "Inception", "year": 2010, "added_at": _iso(now), "rating_key": "9"}]
        transport = FakeTransport([{"data": rows, "meta": {}}])
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items == [
            {
                "media_type": "movie",
                "title": "Inception",
                "added_at": items[0]["added_at"],
                "year": 2010,
                "rating_key": "9",
            }
        ]
        assert transport.calls == ["/recently-added"]


class TestDeduplication:
    """A bulk import appears as episodes *and* their season and show rows."""

    @pytest.mark.unit
    def test_show_and_season_rows_covered_by_episodes_are_dropped(self, monkeypatch):
        """Plex reports one entry per import; counting the raw rows too would double it."""
        now = datetime.now(UTC)
        media, children = TestGrouping._tree()
        rows = [
            _episode("1", "ep-a", now, season_key=SEASON2_ID),
            _episode("2", "ep-b", now - timedelta(minutes=2), season_key=SEASON2_ID),
            {
                "media_type": "season",
                "title": "Saison 2",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "rating_key": SEASON2_ID,
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "year": 2019,
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 1

    @pytest.mark.unit
    def test_a_season_with_no_episodes_in_the_window_is_kept(self, monkeypatch):
        """A season added on its own is real news and must survive the dedup."""
        now = datetime.now(UTC)
        media, children = TestGrouping._tree()
        rows = [
            {
                "media_type": "season",
                "title": "Saison 2",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "rating_key": SEASON2_ID,
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "year": 2019,
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 2
        season = next(i for i in items if i["media_type"] == "season")
        assert season["parent_title"] == "Vinland Saga"
        assert season["media_index"] == 2


class TestEnrichmentResilience:
    """Enrichment is best-effort: a summary with plain titles beats a failed run."""

    @pytest.mark.unit
    def test_lookup_failure_degrades_to_a_bare_title(self, monkeypatch):
        """If the media tree cannot be read, the entry still ships."""
        now = datetime.now(UTC)
        rows = [_episode("1", "ep-a", now, title="Retour au pays")]
        transport = FakeTransport(
            [{"data": rows, "meta": {}}],
            fail_paths=["/media/ep-a"],
        )
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 1
        assert items[0]["title"] == "Retour au pays"
        assert "grandparent_title" not in items[0]

    @pytest.mark.unit
    def test_show_lookups_are_cached_across_entries(self, monkeypatch):
        """Enrichment is per show, not per item — that is what keeps the call count sane."""
        now = datetime.now(UTC)
        media, children = TestGrouping._tree()
        media["ep-b"] = {"id": "ep-b", "media_type": "episode", "show_media_id": SHOW_ID}
        rows = [
            _episode("1", "ep-a", now, season_key=SEASON2_ID),
            _episode("2", "ep-b", now - timedelta(seconds=BURST_GAP_SECONDS * 2), season_key=SEASON2_ID),
        ]
        transport = FakeTransport([{"data": rows, "meta": {}}], media, children)
        client = _client(transport, monkeypatch)

        client.get_items_added_since(_cutoff())

        assert transport.calls.count(f"/media/{SHOW_ID}") == 1
        assert transport.calls.count(f"/media/{SHOW_ID}/children") == 1

    @pytest.mark.unit
    def test_unparseable_payload_is_reported_as_a_value_error(self, monkeypatch):
        """A shape change upstream should fail loudly rather than yield silent nonsense."""
        transport = FakeTransport([{"data": [{"media_type": "movie"}], "meta": {}}])
        client = _client(transport, monkeypatch)

        with pytest.raises(ValueError, match="Unexpected Tracearr response shape"):
            client.get_items_added_since(_cutoff())


class TestFallbackResolution:
    """A show added long ago that just gained episodes is not in the rating-key map."""

    @pytest.mark.unit
    def test_season_resolves_through_an_episode_when_the_show_row_is_absent(self, monkeypatch):
        """Only the episodes are in the window, so the show is reached by climbing."""
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "media_type": "show", "title": "Love, Death & Robots", "year": 2019},
            "ep-a": {"id": "ep-a", "media_type": "episode", "show_media_id": SHOW_ID},
        }
        children = {
            SHOW_ID: [{"id": SEASON2_ID, "media_type": "season", "season_number": 4}],
            SEASON2_ID: [{"id": "ep-a", "media_type": "episode", "episode_number": 1}],
        }
        rows = [
            _episode("1", "ep-a", now, season_key="s-key", show_key="show-key"),
            _episode("2", "ep-b", now - timedelta(minutes=1), season_key="s-key", show_key="show-key"),
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items[0]["media_type"] == "season"
        assert items[0]["parent_title"] == "Love, Death & Robots"
        assert items[0]["media_index"] == 4

    @pytest.mark.unit
    def test_show_entry_falls_back_when_the_key_is_unknown(self, monkeypatch):
        """A multi-season burst still names its show without the show row present."""
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "media_type": "show", "title": "L'Attaque des Titans", "year": 2013},
            "ep-a": {"id": "ep-a", "media_type": "episode", "show_media_id": SHOW_ID},
        }
        rows = [
            _episode("1", "ep-a", now, season_key="s1", show_key="unknown"),
            _episode("2", "ep-b", now - timedelta(minutes=1), season_key="s2", show_key="unknown"),
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, {}), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items[0]["media_type"] == "show"
        assert items[0]["title"] == "L'Attaque des Titans"
        assert items[0]["year"] == 2013

    @pytest.mark.unit
    def test_episode_without_a_media_id_is_left_unenriched(self, monkeypatch):
        """Nothing to climb from, so the entry ships with what the feed gave."""
        now = datetime.now(UTC)
        row = _episode("1", None, now, title="Sans identifiant")
        row.pop("media_id")
        client = _client(FakeTransport([{"data": [row], "meta": {}}]), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items[0]["title"] == "Sans identifiant"
        assert "grandparent_title" not in items[0]

    @pytest.mark.unit
    def test_children_failure_leaves_the_numbering_out(self, monkeypatch):
        """A broken children endpoint must not sink the whole run."""
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "media_type": "show", "title": "Silo", "year": 2023},
            "ep-a": {"id": "ep-a", "media_type": "episode", "show_media_id": SHOW_ID},
        }
        transport = FakeTransport(
            [{"data": [_episode("1", "ep-a", now, title="Adieu")], "meta": {}}],
            media,
            {},
            fail_paths=[f"/media/{SHOW_ID}/children"],
        )
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items[0]["grandparent_title"] == "Silo"
        assert "media_index" not in items[0]


class TestMalformedPayloads:
    """Defensive paths for a source that changes shape."""

    @pytest.mark.unit
    def test_non_object_json_is_rejected(self, monkeypatch):
        """A bare list where an object is expected is a contract break, not data."""
        monkeypatch.setattr("src.tracearr_client.requests.get", lambda *a, **kw: _Response([]))
        monkeypatch.setattr("src.tracearr_client.time.sleep", lambda _s: None)
        client = TracearrClient("http://tracearr:3000", "trr_pub_secret")

        with pytest.raises(ValueError, match="Expected a JSON object"):
            client.get_items_added_since(_cutoff())

    @pytest.mark.unit
    def test_data_must_be_a_list(self, monkeypatch):
        """'data' carrying something other than a list is rejected explicitly."""
        client = _client(FakeTransport([{"data": {"nope": True}, "meta": {}}]), monkeypatch)

        with pytest.raises(ValueError, match="Expected 'data' to be a list"):
            client.get_items_added_since(_cutoff())

    @pytest.mark.unit
    def test_server_id_is_forwarded_when_configured(self, monkeypatch):
        """A multi-server Tracearr needs the summary scoped to one server."""
        transport = FakeTransport([{"data": [], "meta": {}}])
        client = _client(transport, monkeypatch, server_id="srv-1")

        client.get_items_added_since(_cutoff())

        assert transport.params_seen[0]["server_id"] == "srv-1"


class TestDefensivePaths:
    """Branches that only fire when Tracearr misbehaves or a library is enormous."""

    @pytest.mark.unit
    def test_show_lookup_failure_via_the_key_map_is_survivable(self, monkeypatch):
        """The show row is in the feed, but fetching the show itself fails."""
        now = datetime.now(UTC)
        rows = [
            _episode("1", "ep-a", now, season_key="s1", show_key="2947"),
            _episode("2", "ep-b", now - timedelta(minutes=1), season_key="s2", show_key="2947"),
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        transport = FakeTransport([{"data": rows, "meta": {}}], {}, {}, fail_paths=[f"/media/{SHOW_ID}"])
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        # The show entry still ships, named from the episode rather than the show record.
        assert any(i["media_type"] == "show" for i in items)

    @pytest.mark.unit
    def test_season_number_lookup_failure_is_survivable(self, monkeypatch):
        """A season entry ships without its number rather than not at all."""
        now = datetime.now(UTC)
        rows = [
            {
                "media_type": "season",
                "title": "Saison 2",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "rating_key": SEASON2_ID,
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        media = {SHOW_ID: {"id": SHOW_ID, "title": "Vinland Saga"}}
        transport = FakeTransport([{"data": rows, "meta": {}}], media, {}, fail_paths=[f"/media/{SHOW_ID}/children"])
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        season = next(i for i in items if i["media_type"] == "season")
        assert season["parent_title"] == "Vinland Saga"
        assert "media_index" not in season

    @pytest.mark.unit
    def test_seasons_without_an_id_are_skipped(self, monkeypatch):
        """A malformed season entry must not abort the walk for the rest."""
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "title": "Vinland Saga"},
            "ep-a": {"id": "ep-a", "show_media_id": SHOW_ID},
        }
        children = {
            # The id-less season sorts first, so the walk must skip it and carry on.
            SHOW_ID: [{"media_type": "season", "season_number": 9}, {"id": SEASON2_ID, "season_number": 2}],
            SEASON2_ID: [{"id": "ep-a", "episode_number": 7}],
        }
        client = _client(
            FakeTransport([{"data": [_episode("1", "ep-a", now)], "meta": {}}], media, children), monkeypatch
        )

        items = client.get_items_added_since(_cutoff())

        assert items[0]["media_index"] == 7

    @pytest.mark.unit
    def test_page_walk_is_bounded(self, monkeypatch):
        """A cursor that never ends must not spin forever."""
        now = datetime.now(UTC)
        monkeypatch.setattr("src.tracearr_client.MAX_PAGES", 3)
        endless = {
            "data": [{"media_type": "movie", "title": "M", "added_at": _iso(now), "rating_key": "1"}],
            "meta": {"nextCursor": "0"},
        }
        transport = FakeTransport([endless])
        client = _client(transport, monkeypatch)

        client.get_items_added_since(_cutoff())

        assert transport.calls.count("/recently-added") == 3


class TestEdgeBranches:
    """Cases where an optional field is simply absent from the feed."""

    @pytest.mark.unit
    def test_sanitizer_without_a_configured_token(self, monkeypatch):
        """The regex still redacts a token that leaked from somewhere else."""
        monkeypatch.setattr("src.tracearr_client.requests.get", lambda *a, **kw: _Response({}))
        client = TracearrClient("http://tracearr:3000", "")

        assert client._sanitize_error(RuntimeError("saw trr_pub_abc123")) == "saw trr_pub_***"

    @pytest.mark.unit
    def test_movie_without_a_rating_key_is_still_returned(self, monkeypatch):
        """rating_key is optional in the feed; its absence must not drop the entry."""
        now = datetime.now(UTC)
        rows = [{"media_type": "movie", "title": "Sans clé", "added_at": _iso(now)}]
        client = _client(FakeTransport([{"data": rows, "meta": {}}]), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items[0]["title"] == "Sans clé"
        assert "rating_key" not in items[0]

    @pytest.mark.unit
    def test_season_entry_without_a_season_rating_key(self, monkeypatch):
        """A season row missing its own key still renders."""
        now = datetime.now(UTC)
        rows = [
            {
                "media_type": "season",
                "title": "Saison inconnue",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "parent_rating_key": "2947",
            }
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}]), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert items[0]["media_type"] == "season"
        assert "rating_key" not in items[0]

    @pytest.mark.unit
    def test_episodes_without_a_show_key_are_not_grouped(self, monkeypatch):
        """Without a shared show key there is nothing to group on, so each stands alone."""
        now = datetime.now(UTC)
        rows = [
            _episode("1", "ep-a", now, season_key="s1", show_key=None),
            _episode("2", "ep-b", now - timedelta(minutes=1), season_key="s2", show_key=None),
        ]
        for row in rows:
            row["grandparent_rating_key"] = None
        client = _client(FakeTransport([{"data": rows, "meta": {}}]), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert len(items) == 2
        assert {i["media_type"] for i in items} == {"episode"}

    @pytest.mark.unit
    def test_season_cache_is_reused_between_lookups(self, monkeypatch):
        """The show's children are fetched once even when two seasons are resolved."""
        now = datetime.now(UTC)
        media = {SHOW_ID: {"id": SHOW_ID, "title": "Vinland Saga"}}
        children = {
            SHOW_ID: [
                {"id": SEASON1_ID, "season_number": 1},
                {"id": SEASON2_ID, "season_number": 2},
            ]
        }
        rows = [
            {
                "media_type": "season",
                "title": "Saison 1",
                "added_at": _iso(now),
                "media_id": SEASON1_ID,
                "rating_key": "2948",
                "parent_rating_key": "2947",
            },
            {
                "media_type": "season",
                "title": "Saison 2",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "rating_key": "2982",
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        transport = FakeTransport([{"data": rows, "meta": {}}], media, children)
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        assert sorted(i["media_index"] for i in items if i["media_type"] == "season") == [1, 2]
        assert transport.calls.count(f"/media/{SHOW_ID}/children") == 1
        assert transport.calls.count(f"/media/{SHOW_ID}") == 1

    @pytest.mark.unit
    def test_locate_episode_handles_a_show_with_no_seasons(self, monkeypatch):
        """An empty children payload ends the walk instead of looping."""
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "title": "Série vide"},
            "ep-a": {"id": "ep-a", "show_media_id": SHOW_ID},
        }
        client = _client(
            FakeTransport([{"data": [_episode("1", "ep-a", now)], "meta": {}}], media, {SHOW_ID: []}), monkeypatch
        )

        items = client.get_items_added_since(_cutoff())

        assert items[0]["grandparent_title"] == "Série vide"
        assert "media_index" not in items[0]

    @pytest.mark.unit
    def test_season_number_absent_when_no_child_matches(self, monkeypatch):
        """The show has seasons, but none is the one we are looking for."""
        now = datetime.now(UTC)
        media = {SHOW_ID: {"id": SHOW_ID, "title": "Vinland Saga"}}
        children = {SHOW_ID: [{"id": "une-autre-saison", "season_number": 1}]}
        rows = [
            {
                "media_type": "season",
                "title": "Saison 2",
                "added_at": _iso(now),
                "media_id": SEASON2_ID,
                "rating_key": "2982",
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
        ]
        client = _client(FakeTransport([{"data": rows, "meta": {}}], media, children), monkeypatch)

        items = client.get_items_added_since(_cutoff())

        season = next(i for i in items if i["media_type"] == "season")
        assert season["parent_title"] == "Vinland Saga"
        assert "media_index" not in season

    @pytest.mark.unit
    def test_episode_absent_from_every_season(self, monkeypatch):
        """Walking all the seasons without finding the episode leaves it unnumbered."""
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "title": "Silo"},
            "ep-a": {"id": "ep-a", "show_media_id": SHOW_ID},
        }
        children = {
            SHOW_ID: [{"id": SEASON1_ID, "season_number": 1}],
            SEASON1_ID: [{"id": "un-autre-episode", "episode_number": 3}],
        }
        client = _client(
            FakeTransport([{"data": [_episode("1", "ep-a", now)], "meta": {}}], media, children), monkeypatch
        )

        items = client.get_items_added_since(_cutoff())

        assert items[0]["grandparent_title"] == "Silo"
        assert "media_index" not in items[0]

    @pytest.mark.unit
    def test_episode_lookup_reuses_the_cache_filled_by_a_season_entry(self, monkeypatch):
        """
        A season entry and a lone episode of the same show share one children fetch:
        the season path warms the cache and the episode path finds it already there.
        """
        now = datetime.now(UTC)
        media = {
            SHOW_ID: {"id": SHOW_ID, "title": "Vinland Saga"},
            "ep-a": {"id": "ep-a", "show_media_id": SHOW_ID},
        }
        children = {
            SHOW_ID: [
                {"id": SEASON1_ID, "season_number": 1},
                {"id": SEASON2_ID, "season_number": 2},
            ],
            SEASON2_ID: [{"id": "ep-a", "episode_number": 24}],
            SEASON1_ID: [],
        }
        rows = [
            # A season row with no episodes of its own inside the window.
            {
                "media_type": "season",
                "title": "Saison 1",
                "added_at": _iso(now),
                "media_id": SEASON1_ID,
                "rating_key": "2948",
                "parent_rating_key": "2947",
            },
            {
                "media_type": "show",
                "title": "Vinland Saga",
                "added_at": _iso(now),
                "media_id": SHOW_ID,
                "rating_key": "2947",
            },
            # A lone episode from another season of the same show.
            _episode("1", "ep-a", now - timedelta(minutes=1), season_key="2982", show_key="2947"),
        ]
        transport = FakeTransport([{"data": rows, "meta": {}}], media, children)
        client = _client(transport, monkeypatch)

        items = client.get_items_added_since(_cutoff())

        episode = next(i for i in items if i["media_type"] == "episode")
        assert episode["media_index"] == 24
        assert episode["parent_media_index"] == 2
        assert transport.calls.count(f"/media/{SHOW_ID}/children") == 1
