"""Unit tests for Discord client size calculation logic."""

import pytest
from discord_webhook import DiscordEmbed

from src.discord_client import DiscordMediaItem, DiscordNotifier


class TestDiscordNotifier:
    """Tests for DiscordNotifier class."""

    @pytest.fixture
    def notifier(self):
        """Create a DiscordNotifier instance for testing."""
        return DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="https://app.plex.tv",
            media_server_id="test-server-id",
        )

    @pytest.mark.unit
    def test_calculate_embed_size_empty(self, notifier):
        """Test calculating size of an empty embed."""
        embed = DiscordEmbed()
        size = notifier._calculate_embed_size(embed)
        assert size == 0

    @pytest.mark.unit
    def test_calculate_embed_size_with_title(self, notifier):
        """Test calculating size with title."""
        embed = DiscordEmbed(title="Test Title")
        size = notifier._calculate_embed_size(embed)
        assert size == len("Test Title")

    @pytest.mark.unit
    def test_calculate_embed_size_with_description(self, notifier):
        """Test calculating size with description."""
        embed = DiscordEmbed(description="Test Description")
        size = notifier._calculate_embed_size(embed)
        assert size == len("Test Description")

    @pytest.mark.unit
    def test_calculate_embed_size_with_fields(self, notifier):
        """Test calculating size with fields."""
        embed = DiscordEmbed()
        embed.add_embed_field(name="Field 1", value="Value 1")
        embed.add_embed_field(name="Field 2", value="Value 2")

        size = notifier._calculate_embed_size(embed)
        expected = len("Field 1") + len("Value 1") + len("Field 2") + len("Value 2")
        assert size == expected

    @pytest.mark.unit
    def test_calculate_embed_size_with_footer(self, notifier):
        """Test calculating size with footer."""
        embed = DiscordEmbed()
        embed.set_footer(text="Footer text")

        size = notifier._calculate_embed_size(embed)
        assert size == len("Footer text")

    @pytest.mark.unit
    def test_calculate_embed_size_with_author(self, notifier):
        """Test calculating size with author."""
        embed = DiscordEmbed()
        embed.set_author(name="Author Name")

        size = notifier._calculate_embed_size(embed)
        assert size == len("Author Name")

    @pytest.mark.unit
    def test_calculate_embed_size_complete(self, notifier):
        """Test calculating size with all components."""
        embed = DiscordEmbed(title="Test Title", description="Test Description")
        embed.add_embed_field(name="Field", value="Value")
        embed.set_footer(text="Footer")
        embed.set_author(name="Author")

        size = notifier._calculate_embed_size(embed)
        expected = (
            len("Test Title") + len("Test Description") + len("Field") + len("Value") + len("Footer") + len("Author")
        )
        assert size == expected

    @pytest.mark.unit
    def test_calculate_embed_size_with_unicode(self, notifier):
        """Test calculating size with unicode characters."""
        embed = DiscordEmbed(title="🎬 Movies 📺")
        embed.add_embed_field(name="Field 🎵", value="Value 💿")

        size = notifier._calculate_embed_size(embed)
        # Should count by character count, not bytes
        expected = len("🎬 Movies 📺") + len("Field 🎵") + len("Value 💿")
        assert size == expected

    @pytest.mark.unit
    def test_group_items_by_type_movies(self, notifier):
        """Test grouping movie items."""
        items = [
            {"type": "movie", "title": "Movie 1"},
            {"type": "movie", "title": "Movie 2"},
        ]
        grouped = notifier._group_items_by_type(items)
        assert "Movies" in grouped
        assert len(grouped["Movies"]) == 2

    @pytest.mark.unit
    def test_group_items_by_type_tv_shows(self, notifier):
        """Test grouping TV show items."""
        items = [
            {"type": "show", "title": "Show 1"},
            {"type": "season", "title": "Season 1"},
            {"type": "episode", "title": "Episode 1"},
        ]
        grouped = notifier._group_items_by_type(items)
        assert "TV Shows" in grouped
        assert len(grouped["TV Shows"]) == 1
        assert "TV Seasons" in grouped
        assert len(grouped["TV Seasons"]) == 1
        assert "TV Episodes" in grouped
        assert len(grouped["TV Episodes"]) == 1

    @pytest.mark.unit
    def test_group_items_by_type_music(self, notifier):
        """Test grouping music items."""
        items = [
            {"type": "album", "title": "Album 1"},
            {"type": "track", "title": "Track 1"},
        ]
        grouped = notifier._group_items_by_type(items)
        assert "Music Albums" in grouped
        assert len(grouped["Music Albums"]) == 1
        assert "Music Tracks" in grouped
        assert len(grouped["Music Tracks"]) == 1

    @pytest.mark.unit
    def test_group_items_by_type_mixed(self, notifier):
        """Test grouping mixed media types."""
        items = [
            {"type": "movie", "title": "Movie 1"},
            {"type": "show", "title": "Show 1"},
            {"type": "album", "title": "Album 1"},
            {"type": "movie", "title": "Movie 2"},
        ]
        grouped = notifier._group_items_by_type(items)
        assert len(grouped["Movies"]) == 2
        assert len(grouped["TV Shows"]) == 1
        assert len(grouped["Music Albums"]) == 1

    @pytest.mark.unit
    def test_group_items_by_type_unknown(self, notifier):
        """Test grouping with unknown media type — should land in Other, not be dropped."""
        items: list[DiscordMediaItem] = [
            {"type": "audiobook", "title": "Unknown Item"},
        ]
        grouped = notifier._group_items_by_type(items)
        assert len(grouped["Other"]) == 1
        assert grouped["Other"][0]["title"] == "Unknown Item"

    @pytest.mark.unit
    def test_format_media_item_with_link(self, notifier):
        """Test formatting media item with Plex link."""
        item: DiscordMediaItem = {"type": "movie", "rating_key": "12345", "title": "Test Movie"}
        formatted = notifier._format_media_item(item)
        assert "app.plex.tv" in formatted
        assert "test-server-id" in formatted
        assert "12345" in formatted
        assert "Test Movie" in formatted

    @pytest.mark.unit
    def test_format_media_item_without_server_id(self):
        """Test formatting media item without server ID."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="https://app.plex.tv",
            media_server_id=None,
        )
        item: DiscordMediaItem = {"type": "movie", "rating_key": "12345", "title": "Test Movie"}
        formatted = notifier._format_media_item(item)
        assert formatted == "• **Test Movie**"

    @pytest.mark.unit
    def test_format_media_item_missing_rating_key(self, notifier):
        """Test formatting media item without rating_key."""
        item: DiscordMediaItem = {"type": "movie", "title": "Test Movie"}
        formatted = notifier._format_media_item(item)
        assert formatted == "• **Test Movie**"

    @pytest.mark.unit
    def test_validate_and_trim_embed_within_limits(self, notifier):
        """Test that embed within limits is not trimmed."""
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie 1", "added_at": "2024-01-01"},
            {"type": "movie", "title": "Movie 2", "added_at": "2024-01-02"},
        ]

        embed, items_sent = notifier._validate_and_trim_embed(
            category="Movies", items=items, days_back=7, part_num=1, category_total=2, all_items=items
        )

        assert items_sent == 2  # All items should be included
        assert embed is not None

    @pytest.mark.unit
    def test_validate_and_trim_embed_exceeds_limits(self, notifier):
        """Test that oversized embed is trimmed."""
        # Create many items with long titles to exceed size limit
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Very Long Movie Title " * 50, "added_at": f"2024-01-{i:02d}"}  # Very long title
            for i in range(1, 26)  # 25 items (max allowed)
        ]

        embed, items_sent = notifier._validate_and_trim_embed(
            category="Movies", items=items, days_back=7, part_num=1, category_total=25, all_items=items
        )

        # Some items should be trimmed
        assert items_sent < len(items)
        assert embed is not None

        # Embed may still exceed limits if trimming hits minimum size
        size = notifier._calculate_embed_size(embed)
        assert size > 0

    @pytest.mark.unit
    def test_constants_are_within_discord_limits(self):
        """Test that class constants respect Discord API limits."""
        assert DiscordNotifier.MAX_FIELD_VALUE <= 1024
        assert DiscordNotifier.MAX_ITEMS_TOTAL <= 25
        assert DiscordNotifier.MAX_EMBED_SIZE <= 6000
        assert DiscordNotifier.TRIM_REDUCTION_FACTOR > 0
        assert DiscordNotifier.TRIM_REDUCTION_FACTOR < 1

    @pytest.mark.unit
    def test_media_icons_exist(self):
        """Test that media icons are defined for all categories."""
        expected_categories = ["Movies", "TV Shows", "TV Seasons", "TV Episodes", "Music Albums", "Music Tracks"]
        for category in expected_categories:
            assert category in DiscordNotifier.MEDIA_ICONS
            assert isinstance(DiscordNotifier.MEDIA_ICONS[category], str)
            assert len(DiscordNotifier.MEDIA_ICONS[category]) > 0

    @pytest.mark.unit
    def test_send_with_retry_passes_timeout_when_supported(self, notifier):
        """Webhook execution should set timeout attribute when supported."""

        class StubResponse:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self):
                self.timeout = None

            def execute(self):
                return StubResponse()

        webhook = StubWebhook()
        response = notifier._send_with_retry(webhook)

        assert response.status_code == 204
        assert webhook.timeout == notifier.REQUEST_TIMEOUT_SECONDS

    @pytest.mark.unit
    def test_send_summary_no_items_sends_friendly_embed(self, notifier, monkeypatch):
        """No items should trigger a friendly empty-state embed."""

        class StubResponse:
            status_code = 204
            text = ""

            def json(self):
                return {}

        sent_webhooks = []

        class StubWebhook:
            def __init__(self, url):
                self.url = url
                self.embeds = []
                sent_webhooks.append(self)

            def add_embed(self, embed):
                self.embeds.append(embed)

            def execute(self, timeout=None):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        monkeypatch.setattr("src.discord_client.random.choice", lambda choices: choices[0])

        ok = notifier.send_summary(media_items=[], days_back=7, total_count=0)

        assert ok is True
        assert len(sent_webhooks) == 1
        assert len(sent_webhooks[0].embeds) == 1
        embed = sent_webhooks[0].embeds[0]
        assert embed.title == DiscordNotifier.NO_NEW_TITLES[0]
        assert "last 7 days" in embed.description
        assert "add" in embed.description.lower()

    @pytest.mark.unit
    def test_send_summary_no_items_returns_false_on_webhook_failure(self, notifier, monkeypatch):
        """No items empty-state notification should fail cleanly on webhook errors."""

        class StubResponse:
            status_code = 500
            text = "internal error"

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.url = url

            def add_embed(self, embed):
                pass

            def execute(self, timeout=None):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)

        ok = notifier.send_summary(media_items=[], days_back=3, total_count=0)

        assert ok is False

    @pytest.mark.unit
    def test_send_with_retry_respects_rate_limit_429(self, notifier, monkeypatch):
        """_send_with_retry should wait retry_after seconds and retry on 429 responses."""
        sleep_calls: list[float] = []
        monkeypatch.setattr("src.discord_client.time.sleep", lambda s: sleep_calls.append(s))

        attempt = {"n": 0}

        class StubResponse429:
            status_code = 429
            text = ""

            def json(self):
                return {"retry_after": 2.5}

        class StubResponse204:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self):
                self.timeout = None

            def execute(self):
                attempt["n"] += 1
                if attempt["n"] == 1:
                    return StubResponse429()
                return StubResponse204()

        webhook = StubWebhook()
        response = notifier._send_with_retry(webhook, max_retries=3)

        assert response.status_code == 204
        assert attempt["n"] == 2  # one 429, one success
        assert 2.5 in sleep_calls  # waited the retry_after value

    @pytest.mark.unit
    def test_send_with_retry_exhausts_retries_on_persistent_429(self, notifier, monkeypatch):
        """_send_with_retry should return the last response after exhausting retries on persistent 429."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubResponse429:
            status_code = 429
            text = ""

            def json(self):
                return {"retry_after": 0.1}

        class StubWebhook:
            def __init__(self):
                self.timeout = None

            def execute(self):
                return StubResponse429()

        webhook = StubWebhook()
        response = notifier._send_with_retry(webhook, max_retries=3)

        assert response.status_code == 429


class TestSendWithRetryBackoffAndExhaustion:
    """Tests for _send_with_retry exception backoff and re-raise paths."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_retries_with_backoff_then_succeeds(self, notifier, monkeypatch):
        """Should sleep between attempts and succeed on a later attempt."""
        sleep_calls: list[float] = []
        monkeypatch.setattr("src.discord_client.time.sleep", lambda s: sleep_calls.append(s))

        attempt = {"n": 0}

        class StubResponse204:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self):
                self.timeout = None

            def execute(self):
                attempt["n"] += 1
                if attempt["n"] == 1:
                    raise RuntimeError("first attempt fails")
                return StubResponse204()

        response = notifier._send_with_retry(StubWebhook(), max_retries=3)
        assert response.status_code == 204
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == notifier.RETRY_BACKOFF_BASE**0  # 1s

    @pytest.mark.unit
    def test_raises_after_all_retries_exhausted(self, notifier, monkeypatch):
        """Should re-raise the last exception after exhausting all retry attempts."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubWebhook:
            def __init__(self):
                self.timeout = None

            def execute(self):
                raise RuntimeError("persistent failure")

        with pytest.raises(RuntimeError, match="persistent failure"):
            notifier._send_with_retry(StubWebhook(), max_retries=2)


class TestCreateNoNewItemsEmbed:
    """Tests for _create_no_new_items_embed edge cases."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_singular_day_in_description(self, notifier, monkeypatch):
        """days_back=1 should use 'day' instead of 'days' in the description."""
        monkeypatch.setattr("src.discord_client.random.choice", lambda choices: choices[0])
        embed = notifier._create_no_new_items_embed(days_back=1)
        assert "1 day" in embed.description
        assert "1 days" not in embed.description

    @pytest.mark.unit
    def test_plural_days_in_description(self, notifier, monkeypatch):
        """days_back > 1 should use 'days' in the description."""
        monkeypatch.setattr("src.discord_client.random.choice", lambda choices: choices[0])
        embed = notifier._create_no_new_items_embed(days_back=7)
        assert "7 days" in embed.description


class TestFormatMediaItemLocalUrl:
    """Tests for _format_media_item with a local (non-plex.tv) server URL."""

    @pytest.mark.unit
    def test_local_plex_url_uses_web_index_format(self):
        """Local plex URL should produce /web/index.html#!/server/... link format."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="http://192.168.1.100:32400",
            media_server_id="srv-abc",
        )
        item: DiscordMediaItem = {"type": "movie", "rating_key": 99, "title": "Local Movie"}
        formatted = notifier._format_media_item(item)
        assert "192.168.1.100:32400" in formatted
        assert "/web/index.html" in formatted
        assert "srv-abc" in formatted
        assert "99" in formatted

    @pytest.mark.unit
    def test_plex_tv_url_uses_desktop_format(self):
        """plex.tv URL should produce /desktop#!/server/... link format."""
        notifier = DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="https://app.plex.tv",
            media_server_id="srv-xyz",
        )
        item: DiscordMediaItem = {"type": "movie", "rating_key": 1, "title": "Cloud Movie"}
        formatted = notifier._format_media_item(item)
        assert "/desktop" in formatted
        assert "/web/index.html" not in formatted


class TestGetDateRangeFieldName:
    """Tests for _get_date_range_field_name edge cases."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_invalid_date_format_falls_back_to_items_label(self, notifier):
        """Non-ISO date strings should fall back gracefully to 'Items' label."""
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie", "added_at": "not-a-date"},
        ]
        field_name = notifier._get_date_range_field_name(items, chunk_num=1)
        assert field_name == "Items"

    @pytest.mark.unit
    def test_invalid_date_chunk_num_gt_1_uses_items_with_number(self, notifier):
        """Fallback with chunk_num > 1 should include the chunk number."""
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie", "added_at": "bad-date"},
        ]
        field_name = notifier._get_date_range_field_name(items, chunk_num=2)
        assert "Items" in field_name
        assert "2" in field_name

    @pytest.mark.unit
    def test_same_date_returns_single_date(self, notifier):
        """Items all on the same date should return a single DD/MM label."""
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "A", "added_at": "2025-03-15"},
            {"type": "movie", "title": "B", "added_at": "2025-03-15"},
        ]
        field_name = notifier._get_date_range_field_name(items, chunk_num=1)
        assert field_name == "15/03"

    @pytest.mark.unit
    def test_empty_items_chunk_1_returns_items(self, notifier):
        """Empty items list with chunk_num=1 should return the bare 'Items' label."""
        field_name = notifier._get_date_range_field_name([], chunk_num=1)
        assert field_name == "Items"

    @pytest.mark.unit
    def test_empty_items_chunk_gt_1_returns_items_numbered(self, notifier):
        """Empty items list with chunk_num > 1 should return 'Items (N)'."""
        field_name = notifier._get_date_range_field_name([], chunk_num=3)
        assert field_name == "Items (3)"


class TestAddItemsToEmbedFieldSplit:
    """Tests for _add_items_to_embed field overflow splitting."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_splits_into_multiple_fields_when_char_limit_exceeded(self, notifier):
        """Items exceeding MAX_FIELD_VALUE chars should be split across multiple embed fields."""
        from discord_webhook import DiscordEmbed

        # Each item is ~102 chars; 11 × ~102 = ~1122 > 1024 - 50 = 974
        long_title = "A" * 90
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": long_title, "added_at": f"2025-01-{i:02d}"} for i in range(1, 12)
        ]
        embed = DiscordEmbed()
        notifier._add_items_to_embed(embed, items, "Movies")
        assert len(embed.fields) >= 2


class TestValidateAndTrimEmbedCannotReduce:
    """Tests for _validate_and_trim_embed when items cannot be reduced further."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_error_logged_when_single_item_still_too_large(self, notifier, caplog):
        """Should log an error and return the oversized embed when it cannot be trimmed."""
        # Single item with a title large enough to push total embed over MAX_EMBED_SIZE (5800)
        very_long_title = "X" * 6000
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": very_long_title, "added_at": "2025-01-01"},
        ]
        caplog.set_level("ERROR")
        _embed, items_sent = notifier._validate_and_trim_embed(
            category="Movies",
            items=items,
            days_back=7,
            part_num=1,
            category_total=1,
            all_items=items,
        )
        assert items_sent == 1
        assert any("Cannot reduce" in r.message for r in caplog.records)


class TestValidateAndTrimEmbedTrimmedFits:
    """Tests for _validate_and_trim_embed 'trimmed items fit' warning path."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_warning_logged_when_trimmed_items_fit(self, notifier, monkeypatch, caplog):
        """Should log a warning when items are trimmed and the reduced set fits the limit."""
        # Lower the size limit so 5 items exceed it but 4 items (80%) fit under it.
        # Each item "• **Z…Z**" = 4+80+2 = 86 chars; 5 items in a field ≈ 434 chars total field,
        # plus ~80 chars overhead → ~514 chars. After 80% trim (4 items) → ~348 + 80 = ~428 chars.
        monkeypatch.setattr(notifier, "MAX_EMBED_SIZE", 500)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Z" * 80, "added_at": "2025-01-01"} for _ in range(5)
        ]
        caplog.set_level("WARNING")
        _embed, items_sent = notifier._validate_and_trim_embed(
            category="Movies",
            items=items,
            days_back=7,
            part_num=1,
            category_total=5,
            all_items=items,
        )
        assert items_sent < len(items)
        assert any("Trimmed" in r.message and "fit Discord size limit" in r.message for r in caplog.records)


class TestCalculateEmbedSizeEdgeCases:
    """Tests for _calculate_embed_size with null/missing field name, value, footer, and author."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_field_with_none_name_not_counted(self, notifier):
        """A field whose 'name' is None should not contribute to the size."""
        from discord_webhook import DiscordEmbed

        embed = DiscordEmbed()
        embed.fields = [{"name": None, "value": "val", "inline": False}]
        size = notifier._calculate_embed_size(embed)
        assert size == len("val")

    @pytest.mark.unit
    def test_field_with_none_value_not_counted(self, notifier):
        """A field whose 'value' is None should not contribute to the size."""
        from discord_webhook import DiscordEmbed

        embed = DiscordEmbed()
        embed.fields = [{"name": "fld", "value": None, "inline": False}]
        size = notifier._calculate_embed_size(embed)
        assert size == len("fld")

    @pytest.mark.unit
    def test_footer_without_text_not_counted(self, notifier):
        """A footer dict that has no 'text' key should not contribute to the size."""
        from discord_webhook import DiscordEmbed

        embed = DiscordEmbed()
        embed.footer = {"icon_url": "https://example.com/icon.png"}  # truthy, no 'text'
        size = notifier._calculate_embed_size(embed)
        assert size == 0

    @pytest.mark.unit
    def test_author_without_name_not_counted(self, notifier):
        """An author dict that has no 'name' key should not contribute to the size."""
        from discord_webhook import DiscordEmbed

        embed = DiscordEmbed()
        embed.author = {"url": "https://example.com"}  # truthy, no 'name'
        size = notifier._calculate_embed_size(embed)
        assert size == 0


class TestSendWithRetryTimeoutBranches:
    """Tests for _send_with_retry timeout attribute/kwarg dispatch branches."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_execute_called_without_timeout_when_no_attr_and_no_kwarg(self, notifier):
        """When webhook has no timeout attr and no timeout kwarg, execute() called bare."""

        class StubResponse:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            """No timeout attribute, execute() has no timeout kwarg."""

            def execute(self):
                return StubResponse()

        response = notifier._send_with_retry(StubWebhook(), max_retries=1)
        assert response.status_code == 204

    @pytest.mark.unit
    def test_max_retries_zero_raises_value_error(self, notifier):
        """Passing max_retries=0 should raise ValueError immediately."""

        class StubWebhook:
            def execute(self):
                pass  # never reached

        with pytest.raises(ValueError, match="at least 1"):
            notifier._send_with_retry(StubWebhook(), max_retries=0)


class TestSendSummaryNoItemsWith400:
    """Tests for send_summary empty-state path returning 400."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier("https://discord.com/api/webhooks/test")

    @pytest.mark.unit
    def test_400_on_no_items_send_returns_false(self, notifier, monkeypatch, caplog):
        """HTTP 400 for no-items embed should log error and return False."""

        class StubResponse:
            status_code = 400
            text = "Bad Request"

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        caplog.set_level("ERROR")
        result = notifier.send_summary(media_items=[], days_back=7, total_count=0)
        assert result is False
        assert any("invalid payload" in r.message for r in caplog.records)


class TestSendSummaryOuterExceptions:
    """Tests for send_summary outer except handlers (ValueError, Exception)."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="https://app.plex.tv",
            media_server_id="srv",
        )

    @pytest.mark.unit
    def test_value_error_in_send_returns_false(self, notifier, monkeypatch):
        """ValueError propagating out of the send loop should be caught, return False."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)
        monkeypatch.setattr(
            "src.discord_client.DiscordNotifier._group_items_by_type",
            lambda self, items: (_ for _ in ()).throw(ValueError("bad data")),
        )
        items: list[DiscordMediaItem] = [{"type": "movie", "title": "M", "added_at": "2025-01-01"}]
        result = notifier.send_summary(items, days_back=7, total_count=1)
        assert result is False

    @pytest.mark.unit
    def test_generic_exception_in_send_returns_false(self, notifier, monkeypatch):
        """Unexpected Exception in send loop should be caught, return False."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)
        monkeypatch.setattr(
            "src.discord_client.DiscordNotifier._group_items_by_type",
            lambda self, items: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        items: list[DiscordMediaItem] = [{"type": "movie", "title": "M", "added_at": "2025-01-01"}]
        result = notifier.send_summary(items, days_back=7, total_count=1)
        assert result is False


class TestSendSummaryMultiPart:
    """Tests for send_summary multi-part pagination (>MAX_ITEMS_TOTAL items)."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="https://app.plex.tv",
            media_server_id="srv",
        )

    @pytest.mark.unit
    def test_26_items_sends_two_parts(self, notifier, monkeypatch, caplog):
        """26 items in one category should trigger two separate webhook sends."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)
        webhook_executions = {"n": 0}

        class StubResponse:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []
                webhook_executions["n"] += 1

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        caplog.set_level("INFO")

        # 26 movies → first chunk of 25 sent, 1 remainder triggers second send
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": f"Movie {i}", "added_at": f"2025-01-{(i % 28) + 1:02d}"} for i in range(1, 27)
        ]
        result = notifier.send_summary(items, days_back=7, total_count=26)
        assert result is True
        assert webhook_executions["n"] == 2
        # The "part N, M items sent, K remaining" log line should appear
        assert any("remaining" in r.message for r in caplog.records)


class TestSendSummaryWithItems:
    """Tests for send_summary with non-empty media item lists."""

    @pytest.fixture
    def notifier(self):
        return DiscordNotifier(
            webhook_url="https://discord.com/api/webhooks/test",
            media_server_url="https://app.plex.tv",
            media_server_id="srv-id",
        )

    @pytest.mark.unit
    def test_single_category_success_returns_true(self, notifier, monkeypatch):
        """Successful send for a single category should return True."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubResponse:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01", "rating_key": 1},
            {"type": "movie", "title": "Movie B", "added_at": "2025-01-02", "rating_key": 2},
        ]
        result = notifier.send_summary(items, days_back=7, total_count=2)
        assert result is True

    @pytest.mark.unit
    def test_400_response_makes_send_return_false(self, notifier, monkeypatch):
        """HTTP 400 from Discord should break the category loop and return False."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubResponse:
            status_code = 400
            text = "Bad Request"

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01"},
        ]
        result = notifier.send_summary(items, days_back=7, total_count=1)
        assert result is False

    @pytest.mark.unit
    def test_5xx_response_makes_send_return_false(self, notifier, monkeypatch):
        """HTTP 500 from Discord should break the category loop and return False."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubResponse:
            status_code = 500
            text = "Internal Server Error"

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01"},
        ]
        result = notifier.send_summary(items, days_back=7, total_count=1)
        assert result is False

    @pytest.mark.unit
    def test_multiple_categories_each_send_a_message(self, notifier, monkeypatch):
        """Items in two different categories should each produce a separate webhook send."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)
        webhook_count = {"n": 0}

        class StubResponse:
            status_code = 204
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []
                webhook_count["n"] += 1

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01"},
            {"type": "episode", "title": "Show S01E01", "added_at": "2025-01-02"},
        ]
        result = notifier.send_summary(items, days_back=7, total_count=2)
        assert result is True
        assert webhook_count["n"] == 2

    @pytest.mark.unit
    def test_network_exception_from_send_returns_false(self, notifier, monkeypatch):
        """RequestException during send should be caught internally and return False."""
        import requests as _requests

        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                pass

            def execute(self):
                raise _requests.RequestException("connection refused")

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01"},
        ]
        result = notifier.send_summary(items, days_back=7, total_count=1)
        assert result is False

    @pytest.mark.unit
    def test_all_categories_success_logs_summary(self, notifier, monkeypatch, caplog):
        """All messages succeeding should produce the 'All Discord notifications sent' log."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)

        class StubResponse:
            status_code = 200
            text = ""

            def json(self):
                return {}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                return StubResponse()

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01"},
        ]
        caplog.set_level("INFO")
        result = notifier.send_summary(items, days_back=7, total_count=1)
        assert result is True
        assert any("All Discord notifications sent" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_partial_success_logs_warning(self, notifier, monkeypatch, caplog):
        """Partial category failures should produce a warning log."""
        monkeypatch.setattr("src.discord_client.time.sleep", lambda _: None)
        call_count = {"n": 0}

        class StubWebhook:
            def __init__(self, url):
                self.timeout = None
                self.embeds = []

            def add_embed(self, e):
                self.embeds.append(e)

            def execute(self):
                call_count["n"] += 1
                # First category succeeds, second fails
                status = 204 if call_count["n"] == 1 else 500

                class R:
                    status_code: int
                    text = ""

                    def json(self):
                        return {}

                r = R()
                r.status_code = status
                return r

        monkeypatch.setattr("src.discord_client.DiscordWebhook", StubWebhook)
        items: list[DiscordMediaItem] = [
            {"type": "movie", "title": "Movie A", "added_at": "2025-01-01"},
            {"type": "episode", "title": "Show S01E01", "added_at": "2025-01-02"},
        ]
        caplog.set_level("WARNING")
        result = notifier.send_summary(items, days_back=7, total_count=2)
        assert result is False
        assert any("Partial Discord send" in r.message for r in caplog.records)


class TestDeepLinksPerServerType:
    """
    Deep links differ per media server.

    The Plex shapes are verified against a live library; the Jellyfin and Emby ones come
    from their documented URL formats and have not been checked against a real server.
    """

    @pytest.mark.unit
    def test_plex_cloud_link_is_unchanged(self):
        """The app.plex.tv shape must not drift — this is the one in production use."""
        notifier = DiscordNotifier("https://discord.example/x", "https://app.plex.tv", "srv-1")

        link = notifier._build_deep_link("plex", 3007)

        assert link == "https://app.plex.tv/desktop#!/server/srv-1/details?key=%2Flibrary%2Fmetadata%2F3007"

    @pytest.mark.unit
    def test_self_hosted_plex_link_is_unchanged(self):
        """A local Plex uses /web/index.html but the same key format."""
        notifier = DiscordNotifier("https://discord.example/x", "http://plex:32400", "srv-1")

        link = notifier._build_deep_link("plex", 3007)

        assert link == "http://plex:32400/web/index.html#!/server/srv-1/details?key=%2Flibrary%2Fmetadata%2F3007"

    @pytest.mark.unit
    def test_jellyfin_link_uses_the_raw_item_id(self):
        """Jellyfin addresses items by id under #/details, not by library path."""
        notifier = DiscordNotifier("https://discord.example/x", "http://jellyfin:8096", "srv-1")

        link = notifier._build_deep_link("jellyfin", "abc123")

        assert link == "http://jellyfin:8096/web/index.html#/details?id=abc123&serverId=srv-1"

    @pytest.mark.unit
    def test_jellyfin_link_works_without_a_server_id(self):
        """serverId is optional on current Jellyfin, and no source reports one."""
        notifier = DiscordNotifier("https://discord.example/x", "http://jellyfin:8096")

        link = notifier._build_deep_link("jellyfin", "abc123")

        assert link == "http://jellyfin:8096/web/index.html#/details?id=abc123"

    @pytest.mark.unit
    def test_emby_link_uses_its_own_route(self):
        """Emby routes to #!/item where Jellyfin uses #/details."""
        notifier = DiscordNotifier("https://discord.example/x", "http://emby:8096")

        link = notifier._build_deep_link("emby", "abc123")

        assert link == "http://emby:8096/web/index.html#!/item?id=abc123"

    @pytest.mark.unit
    def test_plex_without_a_server_id_yields_no_link(self):
        """Plex cannot be addressed without the server identifier, so no broken URL."""
        notifier = DiscordNotifier("https://discord.example/x", "https://app.plex.tv")

        assert notifier._build_deep_link("plex", 3007) is None

    @pytest.mark.unit
    def test_no_server_url_yields_no_link(self):
        """Nothing to link to."""
        notifier = DiscordNotifier("https://discord.example/x", None, "srv-1")

        assert notifier._build_deep_link("jellyfin", "abc123") is None

    @pytest.mark.unit
    def test_item_without_a_server_type_is_treated_as_plex(self):
        """Tautulli only ever sees Plex and reports no type, so Plex is the default."""
        notifier = DiscordNotifier("https://discord.example/x", "https://app.plex.tv", "srv-1")

        rendered = notifier._format_media_item({"type": "movie", "title": "Inception", "rating_key": 42})

        assert "https://app.plex.tv/desktop#!/server/srv-1/details?key=%2Flibrary%2Fmetadata%2F42" in rendered

    @pytest.mark.unit
    def test_jellyfin_item_renders_a_jellyfin_link(self):
        """The type carried on the payload picks the shape."""
        notifier = DiscordNotifier("https://discord.example/x", "http://jellyfin:8096")

        rendered = notifier._format_media_item(
            {"type": "movie", "title": "Inception", "rating_key": "abc123", "server_type": "jellyfin"}
        )

        assert "http://jellyfin:8096/web/index.html#/details?id=abc123" in rendered
