#!/bin/sh
set -e

# =============================================================================
# Docker Entrypoint Script for Digestarr
# =============================================================================
# Handles PUID/PGID permissions and auto-creates config.yml from template.
# =============================================================================

CONFIG_DIR="/app/configs"
CONFIG_FILE="${CONFIG_DIR}/config.yml"
DEFAULT_CONFIG="/app/config.yml.default"
LOG_DIR="/app/logs"

# Validate that a given ID is a numeric value within the range 1–65535.
# Explicitly rejects 0 (root) for security reasons.
validate_id() {
    value="$1"
    name="$2"

    # Must be composed only of digits.
    case "$value" in
        ''|*[!0-9]*)
            echo "ERROR: $name must be a positive integer, got '$value'." >&2
            exit 1
            ;;
    esac

    # Reject root user/group (UID/GID 0) for security reasons
    if [ "$value" -eq 0 ]; then
        echo "ERROR: $name cannot be 0 (root). Running as root is a security risk." >&2
        echo "       Please specify a non-root user/group ID (1-65535)." >&2
        exit 1
    fi

    # Must be within the typical UID/GID range.
    if [ "$value" -gt 65535 ]; then
        echo "ERROR: $name must be between 1 and 65535, got '$value'." >&2
        exit 1
    fi
}

PUID=${PUID:-99}
PGID=${PGID:-100}

validate_id "$PUID" "PUID"
validate_id "$PGID" "PGID"
echo "Digestarr - starting"
echo "Running with PUID=$PUID, PGID=$PGID"

# Adjust appuser to match PUID/PGID

# Detect current UID/GID for appuser (if it exists)
current_uid="$(id -u appuser 2>/dev/null || echo '')"
current_gid="$(id -g appuser 2>/dev/null || echo '')"

# Handle group (GID)
if [ -z "$current_gid" ] || [ "$current_gid" != "$PGID" ]; then
    existing_group="$(getent group "$PGID" 2>/dev/null | cut -d: -f1 || true)"
    if [ -n "$existing_group" ] && [ "$existing_group" != "appuser" ]; then
        echo "WARNING: Requested PGID $PGID is already used by group '$existing_group'; appuser will share this GID and therefore have the same group permissions as '$existing_group'." >&2
    fi
    if ! groupmod -o -g "$PGID" appuser 2>/dev/null; then
        echo "WARNING: Failed to modify group for appuser; continuing with existing GID '${current_gid:-unknown}'." >&2
    fi
fi

# Handle user (UID)
if [ -z "$current_uid" ] || [ "$current_uid" != "$PUID" ]; then
    existing_user="$(getent passwd "$PUID" 2>/dev/null | cut -d: -f1 || true)"
    if [ -n "$existing_user" ] && [ "$existing_user" != "appuser" ]; then
        echo "WARNING: Requested PUID $PUID is already used by user '$existing_user'; appuser will share this UID, file ownership, and permissions, which may be a security risk if that user has elevated privileges." >&2
    fi
    if ! usermod -o -u "$PUID" appuser 2>/dev/null; then
        echo "WARNING: Failed to modify user for appuser; continuing with existing UID '${current_uid:-unknown}'." >&2
    fi
fi

# Ensure config directory exists and fix permissions
mkdir -p "$CONFIG_DIR"
chown -R "$PUID:$PGID" "$CONFIG_DIR"

# Ensure log directory exists and fix permissions
mkdir -p "$LOG_DIR"
chown -R "$PUID:$PGID" "$LOG_DIR"

# Copy default config if not exists
if [ ! -f "$CONFIG_FILE" ]; then
    cp "$DEFAULT_CONFIG" "$CONFIG_FILE"
    chown "$PUID:$PGID" "$CONFIG_FILE"
    echo "Config created at $CONFIG_FILE"
fi

# Run application as appuser
echo "Starting app"
exec gosu appuser "$@"
