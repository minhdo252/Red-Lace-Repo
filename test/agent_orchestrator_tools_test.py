"""Comprehensive unit tests for the agent orchestrator + tool layer.

Covers every function in app/agent/orchestrator.py and app/agent/tools.py,
normal and edge cases. Runs without the Qdrant/Postgres stack or a live model:
the LLM client, tool dispatch, image reader, and critic are all faked and
restored per-test via the `patched` context manager, so nothing leaks between
tests and no network/db is touched.

Run:
  docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$(pwd)/test:/app/test" \
      --entrypoint python backend test/agent_orchestrator_tools_test.py
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import sys

import app.agent.orchestrator as orch
import app.agent.tools as tools


# ---------------------------------------------------------------------------
# Test harness + fakes
# ---------------------------------------------------------------------------

_MISSING = object()


@contextlib.contextmanager
def patched(module, **attrs):
    """Temporarily set module-level attributes and restore them afterwards, so
    monkeypatched fakes never leak from one test into the next."""
    originals = {name: getattr(module, name, _MISSING) for name in attrs}
    for name, value in attrs.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                delattr(module, name)
            else:
                setattr(module, name, original)


def aio(coro):
    return asyncio.run(coro)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class _FakeCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _ScriptedClient:
    """Returns queued responses in order, one per chat() call, recording every
    message list it was called with (deep-copied at call time)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.tools_seen = []

    async def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        self.tools_seen.append(tools)
        return self._responses.pop(0)


class _AlwaysToolClient:
    """Never returns a final answer — always another tool call. Drives the
    loop-exhaustion path."""

    def __init__(self):
        self.n = 0

    async def chat(self, messages, tools=None):
        self.n += 1
        return _FakeResponse(
            tool_calls=[_FakeCall(f"c{self.n}", "match_scam_pattern", {"text": "x", "category": "price_scam"})]
        )


# ===========================================================================
# orchestrator._is_risk_flag
# ===========================================================================

def test_is_risk_flag_risk_tool_with_flag():
    assert orch._is_risk_flag("compare_price", {"flag": "cao hơn 80%"}) is True


def test_is_risk_flag_risk_tool_with_new_candidate():
    assert orch._is_risk_flag("match_scam_pattern", {"flagged_as_new_candidate": True}) is True


def test_is_risk_flag_risk_tool_no_flag():
    assert orch._is_risk_flag("check_ghost_tour", {"flag": None, "flagged_as_new_candidate": False}) is False


def test_is_risk_flag_risk_tool_empty_result():
    assert orch._is_risk_flag("compare_price", {}) is False


def test_is_risk_flag_non_risk_tool_ignored_even_with_flag():
    # read_image is NOT a risk tool: a stray "flag" key must not trigger the critic.
    assert orch._is_risk_flag("read_image", {"flag": "whatever"}) is False


def test_risk_tools_membership_is_exactly_the_three():
    assert orch.RISK_TOOLS == {"compare_price", "match_scam_pattern", "check_ghost_tour"}


# ===========================================================================
# orchestrator._parse_images_upfront
# ===========================================================================

def test_parse_images_empty_list():
    notes, page, _ = aio(orch._parse_images_upfront([]))
    assert notes == []
    assert page is None


def test_parse_images_dish_note_and_no_page_transparency():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"mode": mode, "text": "MENU"}

    with patched(orch, read_image=fake_read_image):
        notes, page, _ = aio(orch._parse_images_upfront([{"image_base64": b64(b"x"), "mode": "dish"}]))
    assert len(notes) == 1
    assert "read_image mode=dish" in notes[0]
    assert page is None


def test_parse_images_page_transparency_captured():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"risk": "high", "created": "2024"}

    with patched(orch, read_image=fake_read_image):
        _, page, _ = aio(orch._parse_images_upfront([{"image_base64": b64(b"x"), "mode": "page_transparency"}]))
    assert page == {"risk": "high", "created": "2024"}


def test_parse_images_page_transparency_error_not_captured():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"error": "could not parse date"}

    with patched(orch, read_image=fake_read_image):
        notes, page, _ = aio(orch._parse_images_upfront([{"image_base64": b64(b"x"), "mode": "page_transparency"}]))
    assert page is None, "a page_transparency read that errored must not be handed to check_ghost_tour"
    assert "error" in notes[0]


def test_parse_images_latest_page_transparency_wins():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"marker": image_bytes.decode()}

    imgs = [
        {"image_base64": b64(b"first"), "mode": "page_transparency"},
        {"image_base64": b64(b"second"), "mode": "page_transparency"},
    ]
    with patched(orch, read_image=fake_read_image):
        _, page, _ = aio(orch._parse_images_upfront(imgs))
    assert page == {"marker": "second"}


def test_parse_images_read_image_raising_becomes_error_note():
    async def boom(image_bytes, mode, region=None, category="food"):
        raise RuntimeError("vlm exploded")

    with patched(orch, read_image=boom):
        notes, page, _ = aio(orch._parse_images_upfront([{"image_base64": b64(b"x"), "mode": "receipt"}]))
    assert "vlm exploded" in notes[0]
    assert page is None


def test_parse_images_malformed_dict_missing_base64_does_not_crash():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"ok": True}

    # No 'image_base64' key -> KeyError inside the try -> error-as-data note.
    with patched(orch, read_image=fake_read_image):
        notes, page, _ = aio(orch._parse_images_upfront([{"mode": "dish"}]))
    assert len(notes) == 1
    assert "image_base64" in notes[0]
    assert page is None


# ===========================================================================
# orchestrator._run_tool_loop
# ===========================================================================

def test_loop_no_tool_calls_returns_content():
    client = _ScriptedClient([_FakeResponse(content="Xin chao")])
    with patched(orch, ai_client=client):
        final, invoked, risk = aio(orch._run_tool_loop([{"role": "user", "content": "hi"}], None))
    assert final == "Xin chao"
    assert invoked == []
    assert risk is False
    # TOOL_SPECS forwarded to the model on the chat call.
    assert client.tools_seen[0] is tools.TOOL_SPECS


def test_loop_content_none_yields_empty_string():
    client = _ScriptedClient([_FakeResponse(content=None)])
    with patched(orch, ai_client=client):
        final, invoked, risk = aio(orch._run_tool_loop([], None))
    assert final == ""


def test_loop_tool_call_then_final_records_invocation():
    async def fake_call_tool(name, arguments):
        return {"category": name, "ok": True}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "match_scam_pattern", {"text": "t", "category": "price_scam"})]),
        _FakeResponse(content="all good"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        final, invoked, risk = aio(orch._run_tool_loop([], None))
    assert final == "all good"
    assert len(invoked) == 1
    assert invoked[0] == {
        "tool": "match_scam_pattern",
        "arguments": {"text": "t", "category": "price_scam"},
        "result": {"category": "match_scam_pattern", "ok": True},
    }
    assert risk is False  # result carried no flag / new-candidate


def test_loop_risk_flag_detected():
    async def fake_call_tool(name, arguments):
        return {"flag": "cao hơn giá tham chiếu 90%"}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "compare_price", {"item": "pho", "region": "Hanoi"})]),
        _FakeResponse(content="done"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        _, _, risk = aio(orch._run_tool_loop([], None))
    assert risk is True


def test_loop_new_candidate_flag_detected():
    async def fake_call_tool(name, arguments):
        return {"flagged_as_new_candidate": True, "best_score": 0.1}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "match_scam_pattern", {"text": "t", "category": "price_scam"})]),
        _FakeResponse(content="done"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        _, _, risk = aio(orch._run_tool_loop([], None))
    assert risk is True


def test_loop_ghost_tour_injects_page_transparency():
    seen = {}

    async def fake_call_tool(name, arguments):
        seen["name"] = name
        seen["args"] = dict(arguments)
        return {"risk_level": "low"}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "check_ghost_tour", {"url": "http://x"})]),
        _FakeResponse(content="ok"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        _, invoked, _ = aio(orch._run_tool_loop([], {"page": "data"}))
    # The dispatched args got the injected screenshot read...
    assert seen["args"].get("_page_transparency_result") == {"page": "data"}
    # ...but the recorded invocation keeps the model's ORIGINAL arguments.
    assert "_page_transparency_result" not in invoked[0]["arguments"]


def test_loop_ghost_tour_no_injection_when_none():
    seen = {}

    async def fake_call_tool(name, arguments):
        seen["args"] = dict(arguments)
        return {"risk_level": "low"}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "check_ghost_tour", {"url": "http://x"})]),
        _FakeResponse(content="ok"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        aio(orch._run_tool_loop([], None))
    assert "_page_transparency_result" not in seen["args"]


def test_loop_exhaustion_returns_timeout_reply():
    client = _AlwaysToolClient()

    async def fake_call_tool(name, arguments):
        return {}

    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        final, invoked, risk = aio(orch._run_tool_loop([], None))
    assert final == orch.TOOL_LOOP_TIMEOUT_REPLY
    assert client.n == orch.MAX_TOOL_ITERATIONS
    assert len(invoked) == orch.MAX_TOOL_ITERATIONS


def test_loop_multiple_tool_calls_in_one_response():
    async def fake_call_tool(name, arguments):
        return {"tool": name}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[
            _FakeCall("c1", "check_domain_age", {"url": "http://a"}),
            _FakeCall("c2", "check_business_existence", {"name": "b", "region": "Hanoi"}),
        ]),
        _FakeResponse(content="done"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        _, invoked, _ = aio(orch._run_tool_loop([], None))
    assert [i["tool"] for i in invoked] == ["check_domain_age", "check_business_existence"]


def test_loop_appends_assistant_and_tool_messages():
    async def fake_call_tool(name, arguments):
        return {"ok": 1}

    messages = [{"role": "user", "content": "hi"}]
    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "compare_price", {"item": "pho", "region": "Hanoi"})]),
        _FakeResponse(content="done"),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        aio(orch._run_tool_loop(messages, None))
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["tool_calls"][0]["function"]["name"] == "compare_price"
    # arguments are serialized as a JSON string in the assistant message.
    assert json.loads(assistant_msgs[0]["tool_calls"][0]["function"]["arguments"]) == {
        "item": "pho",
        "region": "Hanoi",
    }
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "c1"
    assert json.loads(tool_msgs[0]["content"]) == {"ok": 1}


# ===========================================================================
# orchestrator.handle_turn
# ===========================================================================

def test_handle_turn_plain_text():
    client = _ScriptedClient([_FakeResponse(content="Xin chao!")])
    with patched(orch, ai_client=client):
        result = aio(orch.handle_turn("hello"))
    assert result["reply"] == "Xin chao!"
    assert result["tools_invoked"] == []
    assert "critic" not in result
    # First message is always the system prompt; user text is last.
    first_call = client.calls[0]
    assert first_call[0]["role"] == "system"
    assert first_call[0]["content"] == orch.SYSTEM_PROMPT
    assert first_call[-1] == {"role": "user", "content": "hello"}


def test_handle_turn_includes_history_between_system_and_user():
    client = _ScriptedClient([_FakeResponse(content="ok")])
    history = [{"role": "user", "content": "previous"}, {"role": "assistant", "content": "earlier reply"}]
    with patched(orch, ai_client=client):
        aio(orch.handle_turn("now", history=history))
    msgs = client.calls[0]
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "previous"}
    assert msgs[2] == {"role": "assistant", "content": "earlier reply"}
    assert msgs[-1] == {"role": "user", "content": "now"}


def test_handle_turn_injects_image_notes_before_user_text():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"mode": mode, "text": "receipt total 500k"}

    client = _ScriptedClient([_FakeResponse(content="done")])
    img = {"image_base64": b64(b"x"), "mode": "receipt"}
    with patched(orch, ai_client=client, read_image=fake_read_image):
        aio(orch.handle_turn("what is this", images=[img]))
    msgs = client.calls[0]
    # [system, image_note, user_text]
    assert "read_image mode=receipt" in msgs[-2]["content"]
    assert msgs[-1] == {"role": "user", "content": "what is this"}


def test_handle_turn_risk_flag_runs_critic_with_evidence():
    critic_args = {}

    async def fake_call_tool(name, arguments):
        return {"flag": "cao hơn 80%"}

    async def fake_critic_pass(conclusion, evidence):
        critic_args["conclusion"] = conclusion
        critic_args["evidence"] = evidence
        return {"notes": "reviewed"}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "compare_price", {"item": "pho", "region": "Hanoi", "observed_price": 90000})]),
        _FakeResponse(content="Gia nay cao hon binh thuong."),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool, critic_pass=fake_critic_pass):
        result = aio(orch.handle_turn("is 90k for pho fair?"))
    assert result["critic"] == {"notes": "reviewed"}
    assert result["tools_invoked"][0]["tool"] == "compare_price"
    # Critic receives the final text + the tools_invoked evidence bundle.
    assert critic_args["conclusion"] == "Gia nay cao hon binh thuong."
    assert critic_args["evidence"] == {"tools_invoked": result["tools_invoked"]}


def test_handle_turn_no_risk_no_critic_key():
    async def fake_call_tool(name, arguments):
        return {"flag": None}

    client = _ScriptedClient([
        _FakeResponse(tool_calls=[_FakeCall("c1", "compare_price", {"item": "pho", "region": "Hanoi"})]),
        _FakeResponse(content="Gia binh thuong."),
    ])
    with patched(orch, ai_client=client, call_tool=fake_call_tool):
        result = aio(orch.handle_turn("price?"))
    assert "critic" not in result


# ===========================================================================
# Image region threading + OCR -> compare_price
# ===========================================================================

def test_parse_images_region_threaded_and_ocr_compared():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        assert region == "Hanoi", "region must be threaded into read_image"
        return {
            "mode": mode,
            "source": "qwen_vl",
            "category": "food",
            "ready_items": [{"item_name": "pho bo", "price_vnd": 90000}],
        }

    calls = []

    async def fake_call_tool(name, args):
        calls.append((name, dict(args)))
        return {"flag": None, "reference_price": 40000}

    with patched(orch, read_image=fake_read_image, call_tool=fake_call_tool):
        notes, page, invocations = aio(
            orch._parse_images_upfront([{"image_base64": b64(b"\xff\xd8x"), "mode": "receipt"}], "Hanoi")
        )

    assert calls == [
        ("compare_price", {"item": "pho bo", "region": "Hanoi", "category": "food", "observed_price": 90000})
    ]
    assert invocations[0]["tool"] == "compare_price"
    assert invocations[0]["result"] == {"flag": None, "reference_price": 40000}
    assert any("compare_price item=pho bo" in n for n in notes)
    assert page is None


def test_parse_images_no_region_skips_compare():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"ready_items": [{"item_name": "pho", "price_vnd": 50000}]}

    called = []

    async def fake_call_tool(name, args):
        called.append(name)
        return {}

    with patched(orch, read_image=fake_read_image, call_tool=fake_call_tool):
        _, _, invocations = aio(
            orch._parse_images_upfront([{"image_base64": b64(b"x"), "mode": "receipt"}], None)
        )
    assert invocations == []
    assert called == [], "no region -> OCR/compare must not run"


def test_handle_turn_threads_region_to_image_stage():
    seen = {}

    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        seen["region"] = region
        return {"mode": mode, "text": "ok"}

    client = _ScriptedClient([_FakeResponse(content="done")])
    with patched(orch, ai_client=client, read_image=fake_read_image):
        aio(orch.handle_turn("hi", images=[{"image_base64": b64(b"x"), "mode": "dish"}], region="Sapa"))
    assert seen["region"] == "Sapa"


def test_handle_turn_ocr_price_flag_triggers_critic():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {
            "mode": mode,
            "source": "qwen_vl",
            "category": "food",
            "ready_items": [{"item_name": "pho bo", "price_vnd": 200000}],
        }

    async def fake_call_tool(name, args):
        return {"flag": "cao hơn giá tham chiếu 300%", "reference_price": 50000}

    async def fake_critic_pass(conclusion, evidence):
        return {"notes": "reviewed image price"}

    # Model returns a final answer immediately; the risk comes purely from the
    # OCR-driven compare_price, not from an in-loop tool call.
    client = _ScriptedClient([_FakeResponse(content="Món này khá đắt.")])
    with patched(orch, ai_client=client, read_image=fake_read_image, call_tool=fake_call_tool, critic_pass=fake_critic_pass):
        result = aio(orch.handle_turn(
            "how much?",
            images=[{"image_base64": b64(b"\xff\xd8x"), "mode": "receipt"}],
            region="Hanoi",
        ))
    assert result["critic"] == {"notes": "reviewed image price"}
    assert result["tools_invoked"][0]["tool"] == "compare_price"
    assert result["tools_invoked"][0]["result"]["flag"]


# ===========================================================================
# tools.TOOL_SPECS / TOOL_DISPATCH structure + safety
# ===========================================================================

EXPECTED_TOOL_NAMES = {
    "compare_price",
    "read_image",
    "match_scam_pattern",
    "check_domain_age",
    "check_business_existence",
    "check_ghost_tour",
    "translate_or_get_hotline",
}


def test_tool_specs_are_the_expected_seven():
    names = {spec["name"] for spec in tools.TOOL_SPECS}
    assert names == EXPECTED_TOOL_NAMES, names


def test_every_spec_has_name_description_parameters():
    for spec in tools.TOOL_SPECS:
        assert set(spec) >= {"name", "description", "parameters"}, spec
        assert isinstance(spec["description"], str) and spec["description"], spec["name"]
        assert spec["parameters"]["type"] == "object", spec["name"]


def test_dispatch_and_specs_are_in_lockstep():
    spec_names = {spec["name"] for spec in tools.TOOL_SPECS}
    assert set(tools.TOOL_DISPATCH) == spec_names


def test_trigger_sos_is_structurally_absent():
    assert "trigger_sos" not in tools.TOOL_DISPATCH
    assert "trigger_sos" not in {spec["name"] for spec in tools.TOOL_SPECS}


def test_compare_price_spec_schema():
    spec = next(s for s in tools.TOOL_SPECS if s["name"] == "compare_price")
    props = spec["parameters"]["properties"]
    assert set(props) >= {"item", "region", "category", "observed_price"}
    assert spec["parameters"]["required"] == ["item", "region"]


# ===========================================================================
# tools.call_tool — routing, unknown/disallowed, error-as-data
# ===========================================================================

def test_call_tool_unknown_returns_error():
    result = aio(tools.call_tool("does_not_exist", {}))
    assert result == {"error": "unknown or disallowed tool: does_not_exist"}


def test_call_tool_trigger_sos_disallowed():
    # Safety: even if a model hallucinates the SOS tool name, dispatch refuses it.
    result = aio(tools.call_tool("trigger_sos", {"region": "Hanoi"}))
    assert result == {"error": "unknown or disallowed tool: trigger_sos"}


def test_call_tool_exception_surfaced_as_data():
    async def boom(**kwargs):
        raise ValueError("db down")

    with patched(tools, compare_price=boom):
        result = aio(tools.call_tool("compare_price", {"item": "pho", "region": "Hanoi"}))
    assert result == {"error": "db down"}


def test_call_tool_routes_compare_price():
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"reference_price": 40000}

    with patched(tools, compare_price=fake):
        result = aio(tools.call_tool("compare_price", {"item": "pho bo", "region": "Hanoi", "observed_price": 90000}))
    assert seen == {"item": "pho bo", "region": "Hanoi", "observed_price": 90000}
    assert result == {"reference_price": 40000}


def test_call_tool_routes_match_scam_pattern():
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"category": kwargs.get("category")}

    with patched(tools, match_scam_pattern=fake):
        result = aio(tools.call_tool("match_scam_pattern", {"text": "pay now", "category": "ghost_tour_pressure"}))
    assert seen == {"text": "pay now", "category": "ghost_tour_pressure"}
    assert result == {"category": "ghost_tour_pressure"}


def test_call_tool_routes_check_domain_age():
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"risk": "high"}

    with patched(tools, check_domain_age=fake):
        result = aio(tools.call_tool("check_domain_age", {"url": "http://scam.example"}))
    assert seen == {"url": "http://scam.example"}
    assert result == {"risk": "high"}


def test_call_tool_routes_check_business_existence():
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"status": "found"}

    with patched(tools, check_business_existence=fake):
        result = aio(tools.call_tool("check_business_existence", {"name": "Pho Thin", "region": "Hanoi"}))
    assert seen == {"name": "Pho Thin", "region": "Hanoi"}
    assert result == {"status": "found"}


def test_call_tool_routes_check_ghost_tour():
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"risk_level": "medium"}

    with patched(tools, check_ghost_tour=fake):
        result = aio(tools.call_tool("check_ghost_tour", {"url": "http://fb.com/x", "name": "Sapa Tour"}))
    assert seen == {"url": "http://fb.com/x", "name": "Sapa Tour"}
    assert result == {"risk_level": "medium"}


def test_call_tool_routes_translate_or_get_hotline():
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return {"hotline": "113"}

    with patched(tools, translate_or_get_hotline=fake):
        result = aio(tools.call_tool(
            "translate_or_get_hotline",
            {"text": "help", "region": "Hanoi", "nationality": "KR"},
        ))
    assert seen == {"text": "help", "region": "Hanoi", "nationality": "KR"}
    assert result == {"hotline": "113"}


# ===========================================================================
# tools._dispatch_read_image
# ===========================================================================

def test_dispatch_read_image_decodes_and_passes_mode():
    seen = {}

    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        seen["bytes"] = image_bytes
        seen["mode"] = mode
        return {"text": "ok"}

    with patched(tools, read_image=fake_read_image):
        result = aio(tools._dispatch_read_image({"image_base64": b64(b"hello"), "mode": "page_transparency"}))
    assert seen["bytes"] == b"hello"
    assert seen["mode"] == "page_transparency"
    assert result == {"text": "ok"}


def test_call_tool_read_image_error_surfaced_as_data():
    async def boom(image_bytes, mode):
        raise RuntimeError("ocr failed")

    with patched(tools, read_image=boom):
        result = aio(tools.call_tool("read_image", {"image_base64": b64(b"x"), "mode": "dish"}))
    assert result == {"error": "ocr failed"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
    failures = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((name, f"AssertionError: {exc}"))
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - report any error, keep running
            failures.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        print("FAILURES:")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
        return 1
    print("OK agent_orchestrator_tools_test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
