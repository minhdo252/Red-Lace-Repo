"""Smoke test: the agent's price tool is wired to the real module-2.1
compare_price, not the placeholder estimate_fair_price."""

import asyncio

import app.agent.tools as tools


def test_price_tool_spec_is_compare_price():
    names = {spec["name"] for spec in tools.TOOL_SPECS}
    assert "compare_price" in names, names
    assert "estimate_fair_price" not in names, names
    # Still exactly the 7-tool surface.
    assert names == {
        "compare_price",
        "read_image",
        "match_scam_pattern",
        "check_domain_age",
        "check_business_existence",
        "check_ghost_tour",
        "translate_or_get_hotline",
    }, names


def test_dispatch_routes_to_compare_price():
    seen = {}

    async def fake_compare_price(**kwargs):
        seen.update(kwargs)
        return {"flag": None, "reference_price": 40000}

    # Patch the symbol tools.py dispatches through.
    tools.compare_price = fake_compare_price

    result = asyncio.run(
        tools.call_tool("compare_price", {"item": "pho bo", "region": "Hanoi", "observed_price": 90000})
    )
    assert seen == {"item": "pho bo", "region": "Hanoi", "observed_price": 90000}, seen
    assert result == {"flag": None, "reference_price": 40000}, result


if __name__ == "__main__":
    test_price_tool_spec_is_compare_price()
    test_dispatch_routes_to_compare_price()
    print("OK tools_wiring_test")
