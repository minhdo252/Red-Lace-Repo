#!/usr/bin/env bash
# Container entrypoint. Seed Qdrant `scam_patterns` + Postgres `price_references`
# in the background so they never block the /health check, then serve the API.
# Both seeds are idempotent and always exit 0 (they short-circuit once the data
# exists and read the committed seed_data/ + output/crawled_restaurants_cache.json),
# so re-running them on every boot is safe and cheap after the first time.
( python -u -m app.agent.seed_scam_patterns; python -u -m app.agent.seed_price_references ) &

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
