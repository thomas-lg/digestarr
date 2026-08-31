FROM python:3.14-slim

# Metadata labels
LABEL org.opencontainers.image.title="Plex Releases Summary"
LABEL org.opencontainers.image.description="Fetches recently added Plex media via Tautulli and posts Discord summaries"
LABEL org.opencontainers.image.authors="thomas-lg"
LABEL org.opencontainers.image.url="https://github.com/thomas-lg/plex-releases-summary"
LABEL org.opencontainers.image.source="https://github.com/thomas-lg/plex-releases-summary"
LABEL org.opencontainers.image.documentation="https://github.com/thomas-lg/plex-releases-summary#readme"
LABEL org.opencontainers.image.licenses="MIT"

# Prevent Python from writing bytecode files
ENV PYTHONDONTWRITEBYTECODE=1

# Version injected at build time (e.g. --build-arg VERSION=1.2.3)
ARG VERSION=unknown
ENV APP_VERSION=$VERSION

WORKDIR /app

# Install gosu for privilege dropping
# NOTE: procps is installed to provide the `pgrep` command used in the HEALTHCHECK below.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu procps && \
    rm -rf /var/lib/apt/lists/* && \
    gosu nobody true

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY src/ src/
COPY configs/config.yml config.yml.default
COPY entrypoint.sh .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Create default user (will be modified by entrypoint based on PUID/PGID)
RUN useradd -m -u 1000 appuser

# SECURITY NOTE:
# The entrypoint is invoked as root so it can adjust file ownership/permissions
# according to the requested PUID/PGID before the main process starts. This
# briefly increases the attack surface during initialization, so the logic in
# entrypoint.sh must remain minimal, well-audited, and should drop privileges
# with gosu to the unprivileged user (appuser) as early as possible.
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f "python.*app.py" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "src/app.py"]
