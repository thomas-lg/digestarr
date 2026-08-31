"""Unit tests for configuration module."""

import os
import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from src.config import (
    Config,
    ConfigValue,
    _expand_env_vars,
    _is_env_var_reference,
    _resolve_value,
    get_bootstrap_log_level,
    load_config,
    sync_missing_config_keys,
)


class TestEnvVarReference:
    """Tests for _is_env_var_reference function."""

    @pytest.mark.unit
    def test_valid_env_var_reference(self):
        """Test that valid ${VAR} patterns are detected."""
        assert _is_env_var_reference("${MY_VAR}")
        assert _is_env_var_reference("prefix_${MY_VAR}_suffix")
        assert _is_env_var_reference("${VAR1}_${VAR2}")

    @pytest.mark.unit
    def test_invalid_env_var_reference(self):
        """Test that non-env-var strings are not detected."""
        assert not _is_env_var_reference("plain_string")
        assert not _is_env_var_reference("$VAR")  # Missing braces
        assert not _is_env_var_reference("{VAR}")  # Missing $
        assert not _is_env_var_reference("")
        assert not _is_env_var_reference(123)  # type: ignore


class TestResolveValue:
    """Tests for _resolve_value function."""

    @pytest.mark.unit
    def test_resolve_plain_string(self):
        """Test that plain strings are returned as-is."""
        assert _resolve_value("plain_string") == "plain_string"

    @pytest.mark.unit
    def test_resolve_plain_values(self):
        """Test that non-string values are returned as-is."""
        assert _resolve_value(123) == 123
        assert _resolve_value(True) is True
        assert _resolve_value(None) is None

    @pytest.mark.unit
    def test_resolve_file_path(self):
        """Test reading value from file (Docker secrets pattern)."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("secret_value\n")
            temp_path = f.name

        try:
            result = _resolve_value(temp_path)
            assert result == "secret_value"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_resolve_nonexistent_file_path(self):
        """Test that non-existent file paths are returned as-is."""
        fake_path = "/nonexistent/path/to/secret"
        assert _resolve_value(fake_path) == fake_path

    @pytest.mark.unit
    def test_resolve_dict_recursively(self):
        """Test recursive resolution in dictionaries."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("nested_secret")
            temp_path = f.name

        try:
            data = {"key1": "value1", "key2": temp_path, "nested": {"key3": temp_path}}
            result = _resolve_value(data)
            assert isinstance(result, dict)
            result_dict = cast(dict[str, ConfigValue], result)
            assert result_dict["key1"] == "value1"
            assert result_dict["key2"] == "nested_secret"
            nested = result_dict["nested"]
            assert isinstance(nested, dict)
            nested_dict = cast(dict[str, ConfigValue], nested)
            assert nested_dict["key3"] == "nested_secret"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_resolve_list_recursively(self):
        """Test recursive resolution in lists."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("list_secret")
            temp_path = f.name

        try:
            data = ["value1", temp_path, 123]
            result = _resolve_value(data)
            assert result == ["value1", "list_secret", 123]
        finally:
            Path(temp_path).unlink()


class TestExpandEnvVars:
    """Tests for _expand_env_vars function."""

    @pytest.mark.unit
    def test_expand_defined_env_var(self):
        """Test expansion of defined environment variables."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            data = {"key": "${TEST_VAR}"}
            result = _expand_env_vars(data)
            assert result["key"] == "test_value"

    @pytest.mark.unit
    def test_expand_undefined_env_var_required_field(self):
        """Test that undefined env vars in required fields are kept."""
        data = {"tautulli_url": "${UNDEFINED_VAR}"}
        result = _expand_env_vars(data)
        assert result["tautulli_url"] == "${UNDEFINED_VAR}"

    @pytest.mark.unit
    def test_expand_undefined_env_var_optional_field(self):
        """Test that undefined env vars in optional fields are omitted."""
        data = {"discord_webhook_url": "${UNDEFINED_VAR}"}
        result = _expand_env_vars(data)
        assert "discord_webhook_url" not in result

    @pytest.mark.unit
    def test_expand_empty_env_var_required_field(self):
        """Test that empty env vars in required fields are kept."""
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            data = {"tautulli_url": "${TEST_VAR}"}
            result = _expand_env_vars(data)
            assert result["tautulli_url"] == ""

    @pytest.mark.unit
    def test_expand_empty_env_var_optional_field(self, caplog):
        """Test that empty env vars in optional fields are omitted with warning."""
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            data = {"discord_webhook_url": "${TEST_VAR}"}
            result = _expand_env_vars(data)
            assert "discord_webhook_url" not in result
            assert "defined but empty" in caplog.text

    @pytest.mark.unit
    def test_expand_nested_dict(self):
        """Test recursive expansion in nested dictionaries."""
        with patch.dict(os.environ, {"VAR1": "value1", "VAR2": "value2"}):
            data = {"outer": "${VAR1}", "nested": {"inner": "${VAR2}"}}
            result = _expand_env_vars(data)
            assert result["outer"] == "value1"
            nested = result["nested"]
            assert isinstance(nested, dict)
            nested_dict = cast(dict[str, ConfigValue], nested)
            assert nested_dict["inner"] == "value2"

    @pytest.mark.unit
    def test_expand_list(self):
        """Test expansion in lists."""
        with patch.dict(os.environ, {"VAR1": "value1"}):
            data = cast(dict[str, ConfigValue], {"items": ["${VAR1}", "static", "${VAR1}"]})
            result = _expand_env_vars(data)
            assert result["items"] == ["value1", "static", "value1"]

    @pytest.mark.unit
    def test_list_non_string_items_are_passed_through(self):
        """Non-string list items (int, bool, None) should pass through unchanged."""
        data = cast(dict[str, ConfigValue], {"items": [42, True, None]})
        result = _expand_env_vars(data)
        assert result["items"] == [42, True, None]


class TestConfigModel:
    """Tests for Config Pydantic model validation."""

    @pytest.mark.unit
    def test_minimal_valid_config(self):
        """Test creating config with only required fields."""
        config = Config.model_validate(
            {
                "tautulli_url": "http://localhost:8181",
                "tautulli_api_key": "test_api_key",
                "run_once": True,  # Avoid needing cron_schedule
            }
        )
        assert config.tautulli_url == "http://localhost:8181"
        assert config.tautulli_api_key == "test_api_key"
        assert config.days_back == 7  # Default value
        assert config.run_once is True

    @pytest.mark.unit
    def test_missing_required_field(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate({"tautulli_url": "http://localhost:8181", "run_once": True})  # Missing api_key

        assert "tautulli_api_key" in str(exc_info.value)

    @pytest.mark.unit
    @pytest.mark.parametrize("field", ["tautulli_url", "tautulli_api_key"])
    def test_empty_required_field_rejected(self, field):
        """Test that empty strings for required fields raise ValidationError."""
        data = {
            "tautulli_url": "http://localhost:8181",
            "tautulli_api_key": "test_key",
            "run_once": True,
        }
        data[field] = ""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(data)
        assert field in str(exc_info.value)

    @pytest.mark.unit
    def test_log_level_validation_valid(self):
        """Test that valid log levels are accepted."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = Config.model_validate(
                {
                    "tautulli_url": "http://localhost:8181",
                    "tautulli_api_key": "test_key",
                    "log_level": level,
                    "run_once": True,
                }
            )
            assert config.log_level == level

    @pytest.mark.unit
    def test_log_level_validation_case_insensitive(self):
        """Test that log level validation is case-insensitive."""
        config = Config.model_validate(
            {
                "tautulli_url": "http://localhost:8181",
                "tautulli_api_key": "test_key",
                "log_level": "info",
                "run_once": True,
            }
        )
        assert config.log_level == "INFO"

    @pytest.mark.unit
    def test_log_level_validation_invalid(self):
        """Test that invalid log levels raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "tautulli_url": "http://localhost:8181",
                    "tautulli_api_key": "test_key",
                    "log_level": "INVALID",
                    "run_once": True,
                }
            )

        assert "log_level" in str(exc_info.value)


class TestBootstrapLogLevel:
    """Tests for get_bootstrap_log_level helper."""

    @pytest.mark.unit
    def test_bootstrap_log_level_from_config_file(self):
        """Reads and normalizes a valid log level from config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.safe_dump({"log_level": "debug"}, f)
            temp_path = f.name

        try:
            assert get_bootstrap_log_level(temp_path) == "DEBUG"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_bootstrap_log_level_invalid_value_falls_back_to_info(self):
        """Invalid log level falls back to INFO."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.safe_dump({"log_level": "verbose"}, f)
            temp_path = f.name

        try:
            assert get_bootstrap_log_level(temp_path) == "INFO"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_bootstrap_log_level_missing_file_falls_back_to_info(self):
        """Missing config file falls back to INFO."""
        assert get_bootstrap_log_level("/nonexistent/config.yml") == "INFO"

    @pytest.mark.unit
    def test_bootstrap_log_level_from_env_var(self):
        """Expands env var references in log_level before validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.safe_dump({"log_level": "${TEST_LOG_LEVEL}"}, f)
            temp_path = f.name

        try:
            with patch.dict(os.environ, {"TEST_LOG_LEVEL": "WARNING"}):
                assert get_bootstrap_log_level(temp_path) == "WARNING"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_bootstrap_log_level_non_dict_yaml_falls_back_to_info(self):
        """YAML that is not a mapping (e.g. a list) falls back to INFO."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.safe_dump(["not", "a", "dict"], f)
            temp_path = f.name

        try:
            assert get_bootstrap_log_level(temp_path) == "INFO"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_bootstrap_log_level_unreadable_file_falls_back_to_info(self, tmp_path):
        """File that cannot be read (permissions) falls back to INFO gracefully."""
        secret_file = tmp_path / "config.yml"
        secret_file.write_text("log_level: DEBUG\n")

        with patch.object(Path, "open", side_effect=OSError("Permission denied")):
            assert get_bootstrap_log_level(str(secret_file)) == "INFO"

    @pytest.mark.unit
    def test_bootstrap_log_level_integer_value_falls_back_to_info(self):
        """Non-string log_level (e.g. integer) falls back to INFO."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.safe_dump({"log_level": 10}, f)
            temp_path = f.name

        try:
            assert get_bootstrap_log_level(temp_path) == "INFO"
        finally:
            Path(temp_path).unlink()


class TestConfigValidation:
    """Additional validation tests for Config model."""

    @pytest.mark.unit
    def test_cron_schedule_required_when_not_run_once(self):
        """Test that cron_schedule is required when run_once is False."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "tautulli_url": "http://localhost:8181",
                    "tautulli_api_key": "test_key",
                    "run_once": False,
                    "cron_schedule": None,
                }
            )

        assert "cron_schedule is required" in str(exc_info.value)

    @pytest.mark.unit
    def test_cron_schedule_not_required_when_run_once(self):
        """Test that cron_schedule is optional when run_once is True."""
        config = Config.model_validate(
            {
                "tautulli_url": "http://localhost:8181",
                "tautulli_api_key": "test_key",
                "run_once": True,
                "cron_schedule": None,
            }
        )
        assert config.run_once is True
        assert config.cron_schedule is None

    @pytest.mark.unit
    def test_days_back_validation_positive(self):
        """Test that days_back must be positive."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate(
                {
                    "tautulli_url": "http://localhost:8181",
                    "tautulli_api_key": "test_key",
                    "days_back": 0,
                    "run_once": True,
                }
            )

        assert "days_back" in str(exc_info.value)

    @pytest.mark.unit
    def test_initial_batch_size_validation_range(self):
        """Test that initial_batch_size is within valid range."""
        # Valid range
        config = Config.model_validate(
            {
                "tautulli_url": "http://localhost:8181",
                "tautulli_api_key": "test_key",
                "initial_batch_size": 500,
                "run_once": True,
            }
        )
        assert config.initial_batch_size == 500

        # Too small
        with pytest.raises(ValidationError):
            Config.model_validate(
                {
                    "tautulli_url": "http://localhost:8181",
                    "tautulli_api_key": "test_key",
                    "initial_batch_size": 0,
                    "run_once": True,
                }
            )

        # Too large
        with pytest.raises(ValidationError):
            Config.model_validate(
                {
                    "tautulli_url": "http://localhost:8181",
                    "tautulli_api_key": "test_key",
                    "initial_batch_size": 10001,
                    "run_once": True,
                }
            )

    @pytest.mark.unit
    def test_unresolved_env_var_detection_in_required_fields(self):
        """Test detection of unresolved env vars in required fields."""
        with pytest.raises(ValidationError) as exc_info:
            Config.model_validate({"tautulli_url": "${UNSET_VAR}", "tautulli_api_key": "test_key", "run_once": True})

        error_msg = str(exc_info.value)
        assert "Unresolved environment variable" in error_msg
        assert "${UNSET_VAR}" in error_msg

    @pytest.mark.unit
    def test_default_values(self):
        """Test that default values are correctly applied."""
        config = Config.model_validate(
            {"tautulli_url": "http://localhost:8181", "tautulli_api_key": "test_key", "run_once": True}
        )
        assert config.days_back == 7
        assert config.plex_url == "https://app.plex.tv"
        assert config.log_level == "INFO"
        assert config.discord_webhook_url is None
        assert config.plex_server_id is None


class TestLoadConfig:
    """Tests for load_config function."""

    @pytest.mark.unit
    def test_load_valid_config_file(self):
        """Test loading a valid configuration file."""
        config_data = {
            "tautulli_url": "http://localhost:8181",
            "tautulli_api_key": "test_api_key",
            "run_once": True,
            "days_back": 14,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)
            assert config.tautulli_url == "http://localhost:8181"
            assert config.days_back == 14
            assert config.run_once is True
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_load_config_with_env_vars(self):
        """Test loading config with environment variable interpolation."""
        config_data = {
            "tautulli_url": "${TEST_TAUTULLI_URL}",
            "tautulli_api_key": "${TEST_TAUTULLI_KEY}",
            "run_once": True,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            with patch.dict(os.environ, {"TEST_TAUTULLI_URL": "http://env-url:8181", "TEST_TAUTULLI_KEY": "env-key"}):
                config = load_config(temp_path)
                assert config.tautulli_url == "http://env-url:8181"
                assert config.tautulli_api_key == "env-key"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_load_config_with_docker_secrets(self):
        """Test loading config with Docker secrets (file paths)."""
        # Create secret files
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_file = Path(temp_dir) / "api_key_secret"
            secret_file.write_text("secret_from_file")

            config_data = {
                "tautulli_url": "http://localhost:8181",
                "tautulli_api_key": "${API_KEY_FILE}",
                "run_once": True,
            }

            config_file = Path(temp_dir) / "config.yml"
            config_file.write_text(yaml.dump(config_data))

            with patch.dict(os.environ, {"API_KEY_FILE": str(secret_file)}):
                config = load_config(str(config_file))
                assert config.tautulli_api_key == "secret_from_file"

    @pytest.mark.unit
    def test_load_config_file_not_found(self):
        """Test that FileNotFoundError is raised for missing config."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yml")

    @pytest.mark.unit
    def test_load_config_invalid_yaml(self):
        """Test that invalid YAML raises an error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("invalid: yaml: content: {{{}}")
            temp_path = f.name

        try:
            with pytest.raises(yaml.YAMLError):
                load_config(temp_path)
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_load_config_validation_failure(self):
        """Test that invalid config data raises ValidationError."""
        config_data = {
            "tautulli_url": "http://localhost:8181",
            # Missing required tautulli_api_key
            "run_once": True,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            with pytest.raises(ValidationError):
                load_config(temp_path)
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_load_config_fails_for_missing_required_secret_file(self):
        """Required fields pointing to missing secret files should fail fast."""
        config_data = {
            "tautulli_url": "http://localhost:8181",
            "tautulli_api_key": "/nonexistent/path/to/secret",
            "run_once": True,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="does not exist or is not a regular file"):
                load_config(temp_path)
        finally:
            Path(temp_path).unlink()

    @pytest.mark.unit
    def test_load_config_fails_for_empty_required_secret_file(self):
        """Required fields pointing to empty secret files should fail fast."""
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_secret = Path(temp_dir) / "empty_secret"
            empty_secret.write_text("\n")

            config_data = {
                "tautulli_url": "http://localhost:8181",
                "tautulli_api_key": str(empty_secret),
                "run_once": True,
            }

            config_file = Path(temp_dir) / "config.yml"
            config_file.write_text(yaml.dump(config_data))

            with pytest.raises(ValueError, match="file is empty"):
                load_config(str(config_file))


class TestResolveValueOptionalSecretEdgeCases:
    """Tests for _resolve_value when optional (non-required) secret files have issues."""

    @pytest.mark.unit
    def test_empty_optional_secret_logs_warning_and_returns_path(self, tmp_path, caplog):
        """Empty file for an optional (non-required) field should warn and return original path."""
        empty_file = tmp_path / "empty_opt"
        empty_file.write_text("   \n")

        caplog.set_level("WARNING")
        result = _resolve_value(str(empty_file))  # no required_field
        # Should return the original path unchanged (not raise)
        assert result == str(empty_file)
        assert any("empty" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_os_error_on_optional_secret_logs_warning_and_returns_path(self, tmp_path, caplog):
        """OSError reading an optional field secret file should warn and return original path."""
        secret_file = tmp_path / "secret_opt"
        secret_file.write_text("value")

        with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            caplog.set_level("WARNING")
            result = _resolve_value(str(secret_file))  # no required_field
            assert result == str(secret_file)
            assert any("I/O error" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_unicode_decode_error_in_secret_file_raises_value_error(self, tmp_path):
        """Binary (non-UTF-8) secret file should raise ValueError with helpful message."""
        binary_file = tmp_path / "binary_secret"
        binary_file.write_bytes(b"\xff\xfe\x00")

        with pytest.raises(ValueError, match="not valid text"):
            _resolve_value(str(binary_file))


class TestResolveValueSecretEdgeCases:
    """Tests for _resolve_value edge cases with secret files."""

    @pytest.mark.unit
    def test_oversized_secret_file_raises_value_error(self, tmp_path):
        """Secret file exceeding 10 KB should raise ValueError."""
        large_file = tmp_path / "large_secret"
        large_file.write_bytes(b"x" * (10 * 1024 + 1))  # 10241 bytes

        with pytest.raises(ValueError, match="too large"):
            _resolve_value(str(large_file))

    @pytest.mark.unit
    def test_os_error_on_required_field_raises_value_error(self, tmp_path):
        """OSError reading a required-field secret file should raise ValueError."""
        secret_file = tmp_path / "secret"
        secret_file.write_text("some-secret")

        with (
            patch.object(Path, "read_text", side_effect=OSError("Permission denied")),
            pytest.raises(ValueError, match="could not be read"),
        ):
            _resolve_value(str(secret_file), required_field="tautulli_api_key")

    @pytest.mark.unit
    def test_empty_required_field_secret_raises_value_error(self, tmp_path):
        """Empty secret file for a required field should raise ValueError."""
        empty_file = tmp_path / "empty_secret"
        empty_file.write_text("   \n  ")  # Only whitespace → stripped to ''

        with pytest.raises(ValueError, match="file is empty"):
            _resolve_value(str(empty_file), required_field="tautulli_api_key")


class TestLoadConfigEdgeCases:
    """Tests for load_config edge cases with degenerate YAML inputs."""

    @pytest.mark.unit
    def test_empty_yaml_file_raises_value_error(self, tmp_path):
        """Empty YAML file should raise ValueError (yaml.safe_load returns None)."""
        config_file = tmp_path / "empty.yml"
        config_file.write_text("")

        with pytest.raises(ValueError, match="empty"):
            load_config(str(config_file))

    @pytest.mark.unit
    def test_non_dict_yaml_root_raises_value_error(self, tmp_path):
        """YAML with a list (not mapping) at root should raise ValueError."""
        config_file = tmp_path / "list.yml"
        config_file.write_text(yaml.dump(["item1", "item2"]))

        with pytest.raises(ValueError, match="mapping"):
            load_config(str(config_file))


class TestExcludedMediaTypes:
    """Tests for the excluded_media_types field and its validators."""

    @pytest.mark.unit
    def test_defaults_to_empty_list(self):
        """Test that the field is empty by default, keeping behaviour unchanged."""
        config = Config(tautulli_url="http://localhost:8181", tautulli_api_key="key")
        assert config.excluded_media_types == []

    @pytest.mark.unit
    def test_accepts_valid_types(self):
        """Test that known media types are accepted as a list."""
        config = Config(
            tautulli_url="http://localhost:8181",
            tautulli_api_key="key",
            excluded_media_types=["track", "album"],
        )
        assert config.excluded_media_types == ["track", "album"]

    @pytest.mark.unit
    def test_normalises_case_and_whitespace(self):
        """Test that entries are lowercased and stripped."""
        config = Config(
            tautulli_url="http://localhost:8181",
            tautulli_api_key="key",
            excluded_media_types=["  TRACK ", "Album"],
        )
        assert config.excluded_media_types == ["track", "album"]

    @pytest.mark.unit
    def test_deduplicates_entries(self):
        """Test that repeated types collapse to a single entry."""
        config = Config(
            tautulli_url="http://localhost:8181",
            tautulli_api_key="key",
            excluded_media_types=["track", "TRACK"],
        )
        assert config.excluded_media_types == ["track"]

    @pytest.mark.unit
    def test_rejects_unknown_type(self):
        """Test that an unknown media type fails validation rather than being ignored."""
        with pytest.raises(ValidationError, match="excluded_media_types"):
            Config(
                tautulli_url="http://localhost:8181",
                tautulli_api_key="key",
                excluded_media_types=["movie", "bogus"],
            )

    @pytest.mark.unit
    def test_accepts_comma_separated_string(self):
        """Test the env-var form, where ${VAR} interpolation yields a string."""
        config = Config(
            tautulli_url="http://localhost:8181",
            tautulli_api_key="key",
            excluded_media_types=cast(list[str], "track, album"),
        )
        assert config.excluded_media_types == ["track", "album"]

    @pytest.mark.unit
    def test_empty_string_yields_empty_list(self):
        """Test that an empty env var does not produce a bogus entry."""
        config = Config(
            tautulli_url="http://localhost:8181",
            tautulli_api_key="key",
            excluded_media_types=cast(list[str], ""),
        )
        assert config.excluded_media_types == []

    @pytest.mark.unit
    def test_logs_exclusions_at_startup(self, caplog):
        """Test that load_config reports the configured exclusions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "tautulli_url": "http://localhost:8181",
                        "tautulli_api_key": "key",
                        "excluded_media_types": ["track"],
                    }
                )
            )
            with caplog.at_level("INFO"):
                config = load_config(str(config_path))

        assert config.excluded_media_types == ["track"]
        assert "Excluding media types from the summary: track" in caplog.text


class TestSyncMissingConfigKeys:
    """Tests for reconciling an existing config.yml with the bundled template."""

    TEMPLATE = """# Tautulli instance URL
tautulli_url: ${TAUTULLI_URL}

# Tautulli API key
tautulli_api_key: ${TAUTULLI_API_KEY}

# HTTP health endpoint for container liveness probes
# Default: false
enable_healthcheck: ${ENABLE_HEALTHCHECK}

# Media types to exclude entirely
excluded_media_types: ${EXCLUDED_MEDIA_TYPES}

# A key whose value is a nested block, to prove indented lines are not
# mistaken for top-level keys.
retry:
  attempts: 3
"""

    def _write(self, tmp_path, config_text, template_text=None):
        config_file = tmp_path / "config.yml"
        template_file = tmp_path / "config.yml.default"
        config_file.write_text(config_text, encoding="utf-8")
        template_file.write_text(self.TEMPLATE if template_text is None else template_text, encoding="utf-8")
        return config_file, template_file

    @pytest.mark.unit
    def test_appends_only_missing_keys(self, tmp_path):
        """Keys absent from the user's file are added; existing ones are untouched."""
        config_file, template_file = self._write(
            tmp_path,
            "tautulli_url: ${TAUTULLI_URL}\ntautulli_api_key: ${TAUTULLI_API_KEY}\n",
        )

        added = sync_missing_config_keys(str(config_file), str(template_file))

        assert sorted(added) == ["enable_healthcheck", "excluded_media_types", "retry"]
        text = config_file.read_text(encoding="utf-8")
        assert "enable_healthcheck: ${ENABLE_HEALTHCHECK}" in text
        assert "excluded_media_types: ${EXCLUDED_MEDIA_TYPES}" in text
        # existing keys must not be duplicated
        assert text.count("tautulli_url:") == 1

    @pytest.mark.unit
    def test_reproduces_the_reported_failure(self, tmp_path):
        """
        A pre-v1.4.0 config plus ENABLE_HEALTHCHECK=true must end up enabling the
        endpoint — the exact scenario from the bug report, end to end.
        """
        config_file, template_file = self._write(
            tmp_path,
            "tautulli_url: ${TAUTULLI_URL}\ntautulli_api_key: ${TAUTULLI_API_KEY}\nrun_once: true\n",
        )

        with patch.dict(
            os.environ,
            {
                "TAUTULLI_URL": "http://tautulli:8181",
                "TAUTULLI_API_KEY": "key",
                "ENABLE_HEALTHCHECK": "true",
            },
        ):
            # before the fix this silently loaded enable_healthcheck=False
            assert load_config(str(config_file)).enable_healthcheck is False

            sync_missing_config_keys(str(config_file), str(template_file))

            assert load_config(str(config_file)).enable_healthcheck is True

    @pytest.mark.unit
    def test_carries_the_documenting_comments(self, tmp_path):
        """An appended key keeps the comments that explain it."""
        config_file, template_file = self._write(tmp_path, "tautulli_url: ${TAUTULLI_URL}\n")

        sync_missing_config_keys(str(config_file), str(template_file))

        assert "# HTTP health endpoint for container liveness probes" in config_file.read_text(encoding="utf-8")

    @pytest.mark.unit
    def test_noop_when_nothing_is_missing(self, tmp_path):
        """An up-to-date config is left byte-for-byte alone."""
        config_file, template_file = self._write(tmp_path, self.TEMPLATE)
        before = config_file.read_text(encoding="utf-8")

        assert sync_missing_config_keys(str(config_file), str(template_file)) == []
        assert config_file.read_text(encoding="utf-8") == before

    @pytest.mark.unit
    def test_noop_when_template_absent(self, tmp_path):
        """Outside the image there is no template; this must not be an error."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("tautulli_url: x\n", encoding="utf-8")

        assert sync_missing_config_keys(str(config_file), str(tmp_path / "absent.yml")) == []

    @pytest.mark.unit
    def test_noop_when_config_absent(self, tmp_path):
        """A fresh install is seeded by the entrypoint, not by this function."""
        template_file = tmp_path / "config.yml.default"
        template_file.write_text(self.TEMPLATE, encoding="utf-8")

        assert sync_missing_config_keys(str(tmp_path / "absent.yml"), str(template_file)) == []

    @pytest.mark.unit
    def test_handles_missing_trailing_newline(self, tmp_path):
        """A config not ending in a newline must not have a key glued onto its last line."""
        config_file, template_file = self._write(tmp_path, "tautulli_url: ${TAUTULLI_URL}")

        sync_missing_config_keys(str(config_file), str(template_file))

        assert "tautulli_url: ${TAUTULLI_URL}\n" in config_file.read_text(encoding="utf-8")

    @pytest.mark.unit
    def test_read_only_config_warns_and_continues(self, tmp_path, caplog):
        """An unwritable config must warn with the missing keys, not crash startup."""
        config_file, template_file = self._write(tmp_path, "tautulli_url: ${TAUTULLI_URL}\n")

        real_open = Path.open

        def deny_append(self, mode="r", *args, **kwargs):
            # Only the write-back is denied; reads must still work so the function
            # reaches the append and reports the keys it could not add.
            if "a" in mode:
                raise OSError("read-only file system")
            return real_open(self, mode, *args, **kwargs)

        with patch("pathlib.Path.open", deny_append), caplog.at_level("WARNING"):
            assert sync_missing_config_keys(str(config_file), str(template_file)) == []

        assert "could not be added automatically" in caplog.text
        assert "enable_healthcheck" in caplog.text

    @pytest.mark.unit
    def test_unreadable_files_warn_and_continue(self, tmp_path, caplog):
        """If the config or template cannot be read, startup must proceed regardless."""
        config_file, template_file = self._write(tmp_path, "tautulli_url: ${TAUTULLI_URL}\n")

        with patch("pathlib.Path.read_text", side_effect=OSError("I/O error")), caplog.at_level("WARNING"):
            assert sync_missing_config_keys(str(config_file), str(template_file)) == []

        assert "Could not compare config with the bundled template" in caplog.text

    @pytest.mark.unit
    def test_nested_values_are_not_treated_as_keys(self, tmp_path):
        """Indented lines belong to their parent key and must not become keys of their own."""
        config_file, template_file = self._write(tmp_path, "tautulli_url: ${TAUTULLI_URL}\n")

        added = sync_missing_config_keys(str(config_file), str(template_file))

        assert "attempts" not in added
        assert "retry" in added
        text = config_file.read_text(encoding="utf-8")
        # the nested value is not carried over on its own
        assert "\nattempts:" not in text
