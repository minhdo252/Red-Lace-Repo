# Playwright's own image (not plain python:3.11-slim) so this single image
# can run both the FastAPI backend AND the ShopeeFood crawler/seeding agent
# (backend/app/agent, app/tools, app/utils) — no separate crawler image.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium for the playwright crawler services is installed at runtime by those
# services when needed (FORCE_LIVE_CRAWL); the backend never launches a browser,
# so it's skipped here to keep the image build fast and reliable on the platform.
# RUN playwright install chromium

COPY app ./app
COPY start.sh ./start.sh

# Run as a non-root user matching the typical host UID/GID so bind-mounted
# output (e.g. test/output/ from the crawler services) isn't root-owned.
# The Playwright base image already ships a UID-1000 user (pwuser) — reuse
# it rather than useradd'ing a duplicate at the same UID (fails: "UID 1000
# is not unique"). The crawler docker-compose services override back to
# root at runtime — Chromium in Docker needs root — this default only
# affects `backend` itself.
RUN chown -R pwuser:pwuser /app
USER pwuser

EXPOSE 8000

# start.sh binds the port Railway/host injects via $PORT (falls back to 8000 for
# local/compose), seeds Qdrant + price_references in the background, then serves.
CMD ["bash", "start.sh"]
