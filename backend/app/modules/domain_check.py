"""WHOIS-based domain age check (doc section 7, signal 1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import whois

RISK_THRESHOLD_DAYS = 180


def _extract_domain(url: str) -> str:
    if "://" not in url:
        url = f"https://{url}"
    return urlparse(url).netloc or url


async def check_domain_age(url: str) -> dict[str, Any]:
    domain = _extract_domain(url)
    try:
        record = await asyncio.to_thread(whois.whois, domain)
    except Exception as exc:  # noqa: BLE001 - whois raises many undocumented exception types
        return {"domain": domain, "error": str(exc), "age_days": None, "risk": "unknown"}

    created = record.creation_date
    if isinstance(created, list):
        created = created[0] if created else None
    if created is None:
        return {"domain": domain, "created": None, "age_days": None, "risk": "unknown"}

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - created).days
    risk = "high" if age_days < RISK_THRESHOLD_DAYS else "low"
    return {"domain": domain, "created": created.isoformat(), "age_days": age_days, "risk": risk}
