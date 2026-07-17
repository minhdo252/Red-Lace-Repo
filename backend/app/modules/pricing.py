"""Bayesian fair-price estimation (doc section 6.1).

Log-space Normal-Normal conjugate fusion of an LLM-elicited prior
(p10/p50/p90 + confidence) with real observed data points, updated online.
"""

from __future__ import annotations

import math
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.ai.client import ai_client
from app.db.postgres import get_pool
from app.db.qdrant import get_client

MATCH_THRESHOLD = 0.55
CONFIDENCE_MULTIPLIER = {"low": 1.5, "medium": 1.0, "high": 0.7}
Z90 = 1.2816


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def prior_from_percentiles(p10: float, p50: float, p90: float, confidence: str) -> tuple[float, float]:
    mu0 = math.log(p50)
    sigma0 = (math.log(p90) - math.log(p10)) / (2 * Z90)
    sigma0 *= CONFIDENCE_MULTIPLIER.get(confidence, 1.0)
    return mu0, max(sigma0, 1e-3)


def fuse(mu0: float, sigma0: float, n: int, sum_y: float, sigma_data: float) -> tuple[float, float]:
    """Normal-Normal conjugate update. Returns (mu_post, tau_post)."""
    precision0 = 1.0 / (sigma0 ** 2)
    precision_data = n / (sigma_data ** 2) if n > 0 else 0.0
    posterior_precision = precision0 + precision_data
    ybar = (sum_y / n) if n > 0 else 0.0
    mu_post = (mu0 * precision0 + n * ybar / (sigma_data ** 2 if n > 0 else 1.0)) / posterior_precision
    tau_post = 1.0 / posterior_precision
    return mu_post, tau_post


def z_and_percentile(observed_price: float, mu_post: float, tau_post: float, sigma_data: float) -> tuple[float, float]:
    spread = math.sqrt(tau_post + sigma_data ** 2)
    z = (math.log(observed_price) - mu_post) / spread
    return z, _norm_cdf(z) * 100


async def _get_llm_prior(item: str, region: str) -> dict[str, Any]:
    """Ask the AI client for p10/p50/p90 + confidence. In mock mode this
    returns a fixed placeholder — swap in a real elicitation prompt once
    AIClient.chat is wired to a live model."""
    response = await ai_client.chat(
        [
            {
                "role": "system",
                "content": (
                    "You estimate fair market price ranges for items sold to tourists. "
                    "Respond with p10, p50, p90 (VND) and a confidence level (low/medium/high)."
                ),
            },
            {"role": "user", "content": f"Item: {item}, region: {region}"},
        ]
    )
    # Mock/placeholder fallback until a live model returns structured output.
    return {"p10": 20000, "p50": 40000, "p90": 80000, "confidence": "low", "raw": response.content}


async def estimate_fair_price(item: str, region: str, observed_price: float | None = None) -> dict[str, Any]:
    vector = await ai_client.embed(item)
    qclient = get_client()
    hits = (
        await qclient.query_points(
            collection_name="item_names",
            query=vector,
            query_filter=Filter(must=[FieldCondition(key="region", match=MatchValue(value=region))]),
            limit=1,
        )
    ).points

    pool = get_pool()
    row = None
    if hits and hits[0].score >= MATCH_THRESHOLD:
        postgres_id = hits[0].payload.get("postgres_id")
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM price_references WHERE id = $1", postgres_id)

    if row is not None:
        mu_post, tau_post, sigma_data, n = row["mu_post"], row["tau_post"], row["sigma_data"], row["n"]
        matched = True
    else:
        prior = await _get_llm_prior(item, region)
        mu0, sigma0 = prior_from_percentiles(prior["p10"], prior["p50"], prior["p90"], prior["confidence"])
        sigma_data = 0.3
        mu_post, tau_post = fuse(mu0, sigma0, n=0, sum_y=0.0, sigma_data=sigma_data)
        n = 0
        matched = False

    result: dict[str, Any] = {
        "item": item,
        "region": region,
        "matched_reference": matched,
        "n_data_points": n,
        "fair_price_estimate": round(math.exp(mu_post)),
    }

    if observed_price is not None:
        z, percentile = z_and_percentile(observed_price, mu_post, tau_post, sigma_data)
        result["observed_price"] = observed_price
        result["z_score"] = round(z, 2)
        result["percentile"] = round(percentile, 1)
        result["flag"] = (
            f"cao hơn mức tham khảo (percentile {percentile:.0f}%), độ tin cậy dựa trên {n} điểm dữ liệu"
            if z > Z90
            else None
        )

    return result


async def record_observation(price_reference_id: int, observed_price: float) -> None:
    """Online update: fold one new confirmed data point into a price_reference row. O(1)."""
    y = math.log(observed_price)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM price_references WHERE id = $1", price_reference_id)
        if row is None:
            raise ValueError(f"no price_reference with id {price_reference_id}")
        n = row["n"] + 1
        sum_y = row["sum_y"] + y
        # mu0/sigma0 aren't persisted separately; re-derive an equivalent prior precision
        # from the last posterior so repeated updates stay consistent.
        prior_precision = (1.0 / row["tau_post"]) - (row["n"] / row["sigma_data"] ** 2) if row["tau_post"] else 1.0
        prior_precision = max(prior_precision, 1e-6)
        sigma0 = math.sqrt(1.0 / prior_precision)
        mu_post, tau_post = fuse(row["mu_post"], sigma0, n, sum_y, row["sigma_data"])
        await conn.execute(
            """
            UPDATE price_references
            SET mu_post = $1, tau_post = $2, n = $3, sum_y = $4, updated_at = now()
            WHERE id = $5
            """,
            mu_post,
            tau_post,
            n,
            sum_y,
            price_reference_id,
        )
