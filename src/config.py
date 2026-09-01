"""Configuration module for loading and validating application settings from YAML."""

import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# Type definitions for configuration


class ConfigInput(TypedDict, total=False):
    tautulli_url: str
    tautulli_api_key: str
    days_back: int
    cron_schedule: str | None
    discord_webhook_url: str | None
    media_server_url: str
    media_server_id: str | None
    run_once: bool
    log_level: str
    initial_batch_size: int | None
    excluded_media_types: list[str]
    enable_healthcheck: bool
    health_host: str
    health_port: int


logger = logging.getLogger(__name__)

# Constants
ENV_VAR_PATTERN = re.compile(r"\$\{[^}]+\}")
# Which fields must resolve depends on the selected media source, so this is the
# superset; _required_fields_for() narrows it per source.
REQUIRED_FIELDS = {"tautulli_url", "tautulli_api_key", "tracearr_url", "tracearr_api_key"}
MEDIA_SOURCE_TAUTULLI = "tautulli"
MEDIA_SOURCE_TRACEARR = "tracearr"
_VALID_MEDIA_SOURCES = [MEDIA_SOURCE_TAUTULLI, MEDIA_SOURCE_TRACEARR]
_REQUIRED_BY_SOURCE = {
    MEDIA_SOURCE_TAUTULLI: {"tautulli_url", "tautulli_api_key"},
    MEDIA_SOURCE_TRACEARR: {"tracearr_url", "tracearr_api_key"},
}
DEFAULT_CONFIG_PATH = "/app/configs/config.yml"
# Template baked into the image by the Dockerfile; the source of truth for which
# keys a given version understands.
DEFAULT_CONFIG_TEMPLATE_PATH = "/app/config.yml.default"
TOP_LEVEL_KEY_PATTERN = re.compile(r"^([a-z_][a-z0-9_]*):", re.MULTILINE)

type ConfigScalar = str | int | float | bool | None
type ConfigValue = ConfigScalar | list["ConfigValue"] | dict[str, "ConfigValue"]

_VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Media types Tautulli reports and that the summary knows how to render.
# Kept in sync with the formatting branches in app._format_display_title and
# discord_client.DiscordNotifier._group_items_by_type.
_VALID_MEDIA_TYPES = ["movie", "show", "season", "episode", "album", "track"]


def _validate_log_level_str(v: str) -> str:
    """
    Validate and normalise a log level string.

    Args:
        v: Raw log level string

    Returns:
        Uppercased, validated log level string

    Raises:
        ValueError: If the value is not a recognised Python logging level
    """
    v_upper = v.upper()
    if v_upper not in _VALID_LOG_LEVELS:
        raise ValueError(f"log_level must be one of {_VALID_LOG_LEVELS}, got '{v}'")
    return v_upper


def _is_env_var_reference(value: str) -> bool:
    """
    Check if a string value is an environment variable reference.

    Args:
        value: String to check

    Returns:
        True if value matches ${VAR} pattern, False otherwise
    """
    return isinstance(value, str) and bool(ENV_VAR_PATTERN.search(value))


def _resolve_value(value: ConfigValue, required_field: str | None = None) -> ConfigValue:
    """
    Resolve a configuration value, reading from file if it's a file path.

    If the value is a string starting with '/', attempts to read it as a file path.
    This supports Docker secrets pattern where env vars point to secret files.

    Args:
        value: The value to resolve (can be any type)
        required_field: Required field name for strict secret-file validation

    Returns:
        The resolved value - file contents if applicable, otherwise original value

    Raises:
        ValueError: If secret file exceeds size limit or contains invalid data

    Examples:
        "/run/secrets/api_key" -> reads and returns file content
        "my-api-key" -> returns "my-api-key" as-is
        123 -> returns 123 as-is
    """
    max_secret_size = 10 * 1024  # 10KB max for secret files

    if isinstance(value, str) and value.startswith("/"):
        file_path = Path(value)
        if file_path.exists() and file_path.is_file():
            try:
                # Check file size before reading
                file_size = file_path.stat().st_size
                if file_size > max_secret_size:
                    logger.error(
                        "Secret file %s exceeds maximum size (%d bytes > %d bytes). "
                        "This may not be a valid secret file.",
                        value,
                        file_size,
                        max_secret_size,
                    )
                    raise ValueError(f"Secret file {value} too large: {file_size} bytes")

                content = file_path.read_text().strip()

                # Validate content is reasonable (printable ASCII or UTF-8)
                if not content:
                    if required_field:
                        raise ValueError(
                            f"Required field '{required_field}' references secret file '{value}', "
                            "but the file is empty."
                        )
                    logger.warning("Secret file %s is empty", value)
                    return value

                logger.debug("Successfully read secret from file: %s", value)
                return content
            except OSError as e:
                if required_field:
                    raise ValueError(
                        f"Required field '{required_field}' references secret file '{value}', "
                        f"but it could not be read: {e}"
                    ) from e
                logger.warning("I/O error reading file %s: %s", value, e)
                return value
            except UnicodeDecodeError as e:
                logger.error("Secret file %s contains invalid UTF-8 data: %s", value, e)
                raise ValueError(f"Secret file {value} is not valid text") from None
        else:
            if required_field:
                raise ValueError(
                    f"Required field '{required_field}' references secret file '{value}', "
                    "but the file does not exist or is not a regular file."
                )
            logger.debug("Path %s does not exist, treating as literal value", value)
            return value
    elif isinstance(value, dict):
        return {k: _resolve_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_value(item) for item in value]

    return value


def _expand_env_vars(data: Mapping[str, ConfigValue]) -> dict[str, ConfigValue]:
    """
    Recursively expand environment variables in dictionary values.

    Supports ${VAR} syntax for environment variable substitution.
    After expansion, also resolves any file paths (for secret files).

    For optional fields:
    - Undefined env vars: Silently omitted (Pydantic defaults apply)
    - Empty env vars: Logs WARNING and omitted (possible config mistake)
    For required fields: Undefined/empty env vars are kept and caught by validation.

    Args:
        data: Dictionary with potential ${VAR} references

    Returns:
        Dictionary with all environment variables expanded and files resolved
    """
    expanded: dict[str, ConfigValue] = {}
    for key, value in data.items():
        if isinstance(value, str):
            is_env_var_ref = _is_env_var_reference(value)
            expanded_value = os.path.expandvars(value)

            # Check if there are still unresolved env vars after expansion (undefined)
            if ENV_VAR_PATTERN.search(expanded_value):
                if key in REQUIRED_FIELDS:
                    expanded[key] = expanded_value
                # For optional fields, silently omit (expected behavior)
            # Check if env var expanded to empty string (defined but empty)
            elif is_env_var_ref and expanded_value == "":
                if key in REQUIRED_FIELDS:
                    expanded[key] = expanded_value
                else:
                    logger.warning(
                        "Environment variable for field '%s' is defined but empty. Using default value instead.",
                        key,
                    )
            else:
                required_field = key if key in REQUIRED_FIELDS else None
                expanded[key] = _resolve_value(expanded_value, required_field=required_field)
        elif isinstance(value, dict):
            expanded[key] = _expand_env_vars(value)
        elif isinstance(value, list):
            expanded_list: list[ConfigValue] = []
            for item in value:
                if isinstance(item, str):
                    expanded_item: ConfigValue = os.path.expandvars(item)
                else:
                    expanded_item = item
                expanded_list.append(_resolve_value(expanded_item))
            expanded[key] = expanded_list
        else:
            expanded[key] = value

    return expanded


class Config(BaseModel):
    """
    Application configuration with validation.

    All configuration values are loaded from config.yml with support for:
    - Static values in YAML
    - Environment variable interpolation: ${VAR_NAME}
    - Docker secrets: ${VAR} where VAR points to a file path
    """

    # Media source selection
    media_source: str = Field(
        MEDIA_SOURCE_TAUTULLI,
        description=f"Where recently added media is read from ({', '.join(_VALID_MEDIA_SOURCES)})",
    )

    # Tracearr Configuration (required when media_source is tracearr)
    tracearr_url: str = Field("", description="Full URL to the Tracearr instance (e.g. http://tracearr:3000)")
    tracearr_api_key: str = Field("", description="Tracearr public API token (trr_pub_...)")

    # Tautulli Configuration (required when media_source is tautulli)
    tautulli_url: str = Field("", description="Full URL to Tautulli instance (e.g., http://localhost:8181)")
    tautulli_api_key: str = Field("", description="Tautulli API key for authentication")

    # Core Settings (Optional with defaults)
    days_back: int = Field(default=7, description="Number of days to look back for media releases (default: 7)", ge=1)

    # Scheduling (Optional with defaults)
    cron_schedule: str | None = Field(
        default="0 16 * * SUN",
        description="CRON expression for scheduled execution (default: '0 16 * * SUN' - weekly Sunday 4pm)",
    )

    # Discord Configuration (Optional)
    discord_webhook_url: str | None = Field(None, description="Discord webhook URL for notifications")

    # Plex Configuration (Optional)
    media_server_url: str = Field(
        "https://app.plex.tv",
        description="Media server URL used to build deep links (Plex, Jellyfin or Emby)",
    )
    media_server_id: str | None = Field(
        None,
        description="Media server identifier; required for Plex links, optional for Jellyfin and Emby",
    )

    # Execution Mode (Optional)
    run_once: bool = Field(False, description="Set to true for one-shot execution instead of scheduled")

    # Advanced Settings (Optional)
    log_level: str = Field("INFO", description="Logging verbosity level")
    initial_batch_size: int | None = Field(
        None, description="Override batch size for Tautulli API fetching", ge=1, le=10000
    )
    excluded_media_types: list[str] = Field(
        default_factory=list,
        description=("Media types to omit from the summary entirely " f"(any of: {', '.join(_VALID_MEDIA_TYPES)})"),
    )

    @field_validator("excluded_media_types", mode="before")
    @classmethod
    def coerce_excluded_media_types(cls, v: object) -> object:
        """
        Accept a comma-separated string as well as a YAML list.

        Environment variable interpolation (${EXCLUDED_MEDIA_TYPES}) always yields a
        string, so Docker users can set EXCLUDED_MEDIA_TYPES=track,album and get the
        same result as a YAML list in config.yml.
        """
        if isinstance(v, str):
            return [part for part in (piece.strip() for piece in v.split(",")) if part]
        return v

    @field_validator("excluded_media_types")
    @classmethod
    def validate_excluded_media_types(cls, v: list[str]) -> list[str]:
        """Normalise media types to lowercase and reject unknown ones."""
        normalised: list[str] = []
        for media_type in v:
            candidate = media_type.strip().lower()
            if candidate not in _VALID_MEDIA_TYPES:
                raise ValueError(f"excluded_media_types must contain only {_VALID_MEDIA_TYPES}, got '{media_type}'")
            if candidate not in normalised:
                normalised.append(candidate)
        return normalised

    # Health Endpoint (Optional, scheduled mode only)
    enable_healthcheck: bool = Field(False, description="Serve GET /health for container liveness probes")
    health_host: str = Field(
        "127.0.0.1",
        min_length=1,
        description="Interface the health endpoint binds to; loopback keeps it unreachable from the network",
    )
    health_port: int = Field(8080, description="Port for the health endpoint", ge=1, le=65535)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the standard Python logging levels."""
        return _validate_log_level_str(v)

    @model_validator(mode="after")
    def validate_cron_schedule_required(self) -> Config:
        """Validate that cron_schedule is provided when run_once is False."""
        if not self.run_once and not self.cron_schedule:
            raise ValueError(
                "cron_schedule is required when run_once is False. "
                "Either set run_once: true or provide a cron_schedule."
            )
        return self

    @field_validator("media_source")
    @classmethod
    def validate_media_source(cls, v: str) -> str:
        """Normalise the media source and reject anything unimplemented."""
        candidate = v.strip().lower()
        if candidate not in _VALID_MEDIA_SOURCES:
            raise ValueError(f"media_source must be one of {_VALID_MEDIA_SOURCES}, got '{v}'")
        return candidate

    @model_validator(mode="after")
    def validate_selected_source_is_configured(self) -> Config:
        """
        Require only the fields the selected source actually needs.

        The unselected source's fields may legitimately be blank, or still hold an
        unresolved ${VAR} reference because REQUIRED_FIELDS covers both sources.
        """
        for field_name in sorted(_REQUIRED_BY_SOURCE[self.media_source]):
            value = getattr(self, field_name)
            if not value:
                raise ValueError(
                    f"{field_name} is required when media_source is '{self.media_source}'. "
                    "Set it in config.yml or via its environment variable."
                )
            match = ENV_VAR_PATTERN.search(value)
            if match:
                raise ValueError(
                    f"Unresolved environment variable: {match.group(0)} in required field "
                    f"'{field_name}'. Ensure the environment variable is set or provide a "
                    "value in config.yml."
                )

        return self


def _extract_key_blocks(template: str) -> dict[str, str]:
    """
    Split a config template into per-key blocks, each carrying its own comments.

    The comment lines immediately above a key document what it does, so they travel
    with the key when it is copied into a user's config.

    Args:
        template: Full text of the template file

    Returns:
        Mapping of top-level key name to its comment block plus key line
    """
    blocks: dict[str, str] = {}
    pending: list[str] = []

    for line in template.splitlines():
        if line.startswith("#"):
            pending.append(line)
            continue
        if not line.strip():
            # A blank line ends a comment block that is not attached to a key.
            pending = []
            continue

        match = TOP_LEVEL_KEY_PATTERN.match(line)
        if match:
            blocks[match.group(1)] = "\n".join([*pending, line])
        pending = []

    return blocks


def sync_missing_config_keys(
    config_path: str = DEFAULT_CONFIG_PATH,
    template_path: str = DEFAULT_CONFIG_TEMPLATE_PATH,
) -> list[str]:
    """
    Append config keys the installed version knows about but the user's file lacks.

    The entrypoint only seeds config.yml when it is absent, so an installation that
    predates a release keeps a file without the newer keys. Since environment
    variables reach the app only through ${VAR} references inside that file, those
    settings would otherwise be silently unreachable.

    Existing content is never modified - keys are only appended, with the comments
    that document them.

    Args:
        config_path: Path to the user's config.yml
        template_path: Path to the version's template (config.yml.default)

    Returns:
        The key names that were added, empty if there was nothing to do
    """
    config_file = Path(config_path)
    template_file = Path(template_path)

    if not config_file.exists() or not template_file.exists():
        # Fresh installs are seeded from the template by the entrypoint, and the
        # template is absent outside the image (e.g. local development).
        return []

    try:
        existing = config_file.read_text()
        template = template_file.read_text()
    except OSError as e:
        logger.warning("Could not compare config with the bundled template: %s", e)
        return []

    existing_keys = set(TOP_LEVEL_KEY_PATTERN.findall(existing))
    blocks = _extract_key_blocks(template)
    missing = [key for key in blocks if key not in existing_keys]

    if not missing:
        return []

    header = (
        "# ---------------------------------------------------------------------------\n"
        "# Added automatically on upgrade: settings this version understands that were\n"
        "# missing from your config. Edit or remove them as you would any other field.\n"
        "# ---------------------------------------------------------------------------\n"
    )
    addition = "\n\n".join(blocks[key] for key in missing)
    separator = "" if existing.endswith("\n") else "\n"

    try:
        with config_file.open("a", encoding="utf-8") as f:
            f.write(f"{separator}\n{header}{addition}\n")
    except OSError as e:
        logger.warning(
            "New settings (%s) are missing from %s and could not be added automatically: %s. "
            "Add them by hand to configure these options.",
            ", ".join(missing),
            config_path,
            e,
        )
        return []

    logger.info("Added new settings to %s: %s", config_path, ", ".join(missing))
    return missing


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Config:
    """
    Load and validate configuration from YAML file.

    Supports:
    - Environment variable interpolation: ${VAR_NAME}
    - Docker secrets: variables pointing to file paths are automatically read

    Args:
        config_path: Path to config.yml file (default: /app/configs/config.yml)

    Returns:
        Validated Config instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML parsing fails
        pydantic.ValidationError: If configuration validation fails

    Examples:
        >>> config = load_config()
        >>> print(config.tautulli_url)
        http://localhost:8181
    """
    config_file = Path(config_path)

    if not config_file.exists():
        error_msg = (
            f"Configuration file not found: {config_path}\n"
            "Please create a config.yml file based on configs/config.yml in the repository."
        )
        raise FileNotFoundError(error_msg)

    logger.info("Loading configuration from %s", config_path)
    with config_file.open("r") as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        raise ValueError("Configuration file is empty")
    if not isinstance(raw_config, dict):
        raise ValueError("config.yml must contain a mapping/object at the root " "(not a list, string, or other type)")

    # Expand environment variables and resolve file paths
    expanded_config = cast(ConfigInput, _expand_env_vars(raw_config))

    # Validate and create Config instance
    config = Config.model_validate(expanded_config)

    logger.info("✅ Configuration loaded and validated successfully")
    logger.info(
        "Config: source=%s, days_back=%d, log_level=%s, run_once=%s, discord=%s, cron=%s",
        config.media_source,
        config.days_back,
        config.log_level,
        config.run_once,
        "configured" if config.discord_webhook_url else "not configured",
        config.cron_schedule if not config.run_once else "N/A (run_once)",
    )
    if config.excluded_media_types:
        logger.info("Excluding media types from the summary: %s", ", ".join(config.excluded_media_types))

    return config


def get_bootstrap_log_level(config_path: str = DEFAULT_CONFIG_PATH) -> str:
    """
    Read log_level from config file before full validation.

    This enables early logger setup so load-time logs can honor configured verbosity.
    Falls back to INFO for any missing/invalid/unreadable value.

    Args:
        config_path: Path to config.yml file

    Returns:
        Uppercased log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            return "INFO"

        with config_file.open("r") as f:
            raw_config = yaml.safe_load(f)

        if not isinstance(raw_config, dict):
            return "INFO"

        expanded = _expand_env_vars({"log_level": raw_config.get("log_level", "INFO")})
        level = expanded.get("log_level", "INFO")

        if not isinstance(level, str):
            return "INFO"

        return _validate_log_level_str(level.strip())
    except Exception:
        return "INFO"
