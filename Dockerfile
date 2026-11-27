# UAV Downloader CLI + opt-in authenticated NAS Web queue.
# Pass URL(s); videos are downloaded to /downloads without a GUI.
FROM python:3.12-slim

# ffmpeg = TS->MP4 remux + on-demand HLS transcoding; VAAPI drivers let
# ffmpeg use Intel QuickSync when /dev/dri is passed through at runtime.
# ca-certificates = TLS. Slim + cleaned apt lists.
# Enable contrib/non-free too (intel-media-va-driver lives there on some
# Debian suites). The VAAPI drivers are best-effort only — without them the
# web player falls back to software transcoding — so never fail the build.
RUN sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources || true
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates \
    && (apt-get install -y --no-install-recommends \
        intel-media-va-driver i965-va-driver \
        || echo 'WARN: VAAPI drivers not installed; software transcoding will be used') \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# deps first for layer caching
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .

ENV DOWNLOAD_DIR=/downloads \
    UAV_WEB_STATE_DIR=/state \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    UAV_LANG=zh-Hans
VOLUME ["/downloads"]
EXPOSE 8765

# URL(s) are passed as CMD args (or via URLS / URLS_FILE env)
ENTRYPOINT ["python", "-u", "-m", "uav_downloader.cli.headless"]
