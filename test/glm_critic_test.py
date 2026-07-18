"""Unit tests for the GLM-5.2 client parsing and the module-output-injecting
critic. Offline: no network, no key — glm_chat/has_api_key are monkeypatched and
the OpenAI response objects are faked."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from types import SimpleNamespace as NS

import app.ai.glm_chat as glm
import app.agent.critic as critic
from app.ai.glm_chat import GlmResponse

_MISSING = object()


@contextlib.contextmanager
def patched(module, **attrs):
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


def _fake_openai_response(content=None, reasoning=None, tool_calls=None, finish_reason="stop"):
    message = NS(content=content, reasoning_content=reasoning, tool_calls=tool_calls)
    return NS(choices=[NS(message=message, finish_reason=finish_reason)])


def _fake_tool_call(id, name, arguments):
    return NS(id=id, function=NS(name=name, arguments=arguments))


# ===========================================================================
# glm_chat.parse_response — reasoning model content/reasoning/tool split
# ===========================================================================

def test_parse_splits_content_and_reasoning():
    resp = _fake_openai_response(content="PONG", reasoning="let me think... PONG")
    parsed = glm.parse_response(resp)
    assert parsed.content == "PONG"
    assert parsed.reasoning == "let me think... PONG"
    assert parsed.tool_calls == []
    assert parsed.finish_reason == "stop"


def test_parse_empty_content_is_empty_string_not_none():
    # Small max_tokens on a reasoning model => reasoning eats the budget, content is None.
    resp = _fake_openai_response(content=None, reasoning="thinking with no room left")
    parsed = glm.parse_response(resp)
    assert parsed.content == ""
    assert parsed.reasoning.startswith("thinking")


def test_parse_tool_calls():
    resp = _fake_openai_response(
        content=None,
        tool_calls=[_fake_tool_call("c1", "compare_price", '{"item":"pho","region":"Hanoi","observed_price":90000}')],
        finish_reason="tool_calls",
    )
    parsed = glm.parse_response(resp)
    assert len(parsed.tool_calls) == 1
    tc = parsed.tool_calls[0]
    assert tc.id == "c1" and tc.name == "compare_price"
    assert tc.arguments == {"item": "pho", "region": "Hanoi", "observed_price": 90000}


def test_parse_tool_call_bad_json_is_raw():
    resp = _fake_openai_response(tool_calls=[_fake_tool_call("c1", "x", "{not json}")])
    parsed = glm.parse_response(resp)
    assert parsed.tool_calls[0].arguments == {"_raw": "{not json}"}


def test_parse_missing_tool_call_id_gets_synthetic():
    resp = _fake_openai_response(tool_calls=[_fake_tool_call(None, "x", "{}")])
    parsed = glm.parse_response(resp)
    assert parsed.tool_calls[0].id == "call_0"


# ===========================================================================
# glm_chat.assemble_stream — streaming reassembly (default path)
# ===========================================================================

def _chunk(content=None, reasoning=None, tool_calls=None, finish_reason=None):
    delta = NS(content=content, reasoning_content=reasoning, tool_calls=tool_calls)
    return NS(choices=[NS(delta=delta, finish_reason=finish_reason)])


def _empty_chunk():
    return NS(choices=[])


def _tc_delta(index, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


def test_stream_assembles_content_and_reasoning():
    stream = [
        _empty_chunk(),
        _chunk(reasoning="think "),
        _chunk(reasoning="more"),
        _chunk(content="PO"),
        _chunk(content="NG", finish_reason="stop"),
    ]
    r = glm.assemble_stream(iter(stream))
    assert r.content == "PONG"
    assert r.reasoning == "think more"
    assert r.finish_reason == "stop"
    assert r.tool_calls == []


def test_stream_assembles_tool_call_arguments_across_chunks():
    stream = [
        _chunk(tool_calls=[_tc_delta(0, id="c1", name="compare_price", arguments='{"item":"bún ')]),
        _chunk(tool_calls=[_tc_delta(0, arguments='chả","region":"Hanoi"}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    r = glm.assemble_stream(iter(stream))
    assert len(r.tool_calls) == 1
    tc = r.tool_calls[0]
    assert tc.id == "c1" and tc.name == "compare_price"
    assert tc.arguments == {"item": "bún chả", "region": "Hanoi"}
    assert r.finish_reason == "tool_calls"


def test_stream_multiple_tool_calls_kept_by_index():
    stream = [
        _chunk(tool_calls=[_tc_delta(0, id="a", name="check_domain_age", arguments='{"url":"x"}')]),
        _chunk(tool_calls=[_tc_delta(1, id="b", name="compare_price", arguments='{"item":"y","region":"Hanoi"}')]),
    ]
    r = glm.assemble_stream(iter(stream))
    assert [t.name for t in r.tool_calls] == ["check_domain_age", "compare_price"]
    assert r.tool_calls[1].arguments == {"item": "y", "region": "Hanoi"}


def test_stream_missing_tool_id_gets_synthetic():
    stream = [_chunk(tool_calls=[_tc_delta(0, name="x", arguments="{}")])]
    r = glm.assemble_stream(iter(stream))
    assert r.tool_calls[0].id == "call_0"


# ===========================================================================
# critic._format_module_outputs
# ===========================================================================

def test_format_empty_module_outputs():
    assert critic._format_module_outputs([]) == "(no module outputs this turn)"


def test_format_labels_each_module_with_input_and_output():
    invocations = [
        {"tool": "compare_price", "arguments": {"item": "pho", "region": "Hanoi"}, "result": {"flag": "121% over"}},
        {"tool": "match_scam_pattern", "arguments": {"text": "pay now"}, "result": {"best_score": 0.8}},
    ]
    block = critic._format_module_outputs(invocations)
    assert "module=compare_price" in block
    assert "module=match_scam_pattern" in block
    assert "121% over" in block
    assert "0.8" in block
    assert "[1]" in block and "[2]" in block


# ===========================================================================
# critic_pass — injection + key gating
# ===========================================================================

def test_critic_no_key_returns_unreviewed():
    with patched(critic, has_api_key=lambda: False):
        result = aio(critic.critic_pass("This price looks too high.", {"tools_invoked": [{"tool": "compare_price", "result": {"flag": "x"}}]}))
    assert result["verdict"] == "unreviewed"
    assert result["degraded"] is True
    assert "GLM_API_KEY" in result["notes"]


def test_critic_injects_every_module_output_and_returns_notes():
    captured = {}

    def fake_glm_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return GlmResponse(content="The 121% markup is well above reference; warning is justified. Innocent explanation unlikely given the gap.", reasoning="chain of thought")

    evidence = {
        "tools_invoked": [
            {"tool": "compare_price", "arguments": {"item": "phở bò", "region": "Hanoi", "observed_price": 90000}, "result": {"flag": "cao hơn 121%", "reference_price": 40660}},
            {"tool": "check_ghost_tour", "arguments": {"name": "X Tour"}, "result": {"risk_level": "low", "safety": {"label": "Không an toàn"}}},
        ]
    }
    with patched(critic, has_api_key=lambda: True, glm_chat=fake_glm_chat):
        result = aio(critic.critic_pass("Giá này cao hơn bình thường.", evidence))

    # Return shape
    assert result["verdict"] == "reviewed"
    assert result["notes"].startswith("The 121% markup")
    assert result["reasoning"] == "chain of thought"

    # Every module output was injected into the prompt the model saw.
    user_msg = next(m["content"] for m in captured["messages"] if m["role"] == "user")
    assert "Giá này cao hơn bình thường." in user_msg
    assert "module=compare_price" in user_msg
    assert "module=check_ghost_tour" in user_msg
    assert "cao hơn 121%" in user_msg
    assert "Không an toàn" in user_msg
    # Reasoning model needs a real token budget.
    assert captured["kwargs"].get("max_tokens", 0) >= 512


def test_critic_empty_content_falls_back_to_note():
    def fake_glm_chat(messages, **kwargs):
        return GlmResponse(content="", reasoning="only reasoning, no final answer")

    with patched(critic, has_api_key=lambda: True, glm_chat=fake_glm_chat):
        result = aio(critic.critic_pass("x", {"tools_invoked": []}))
    assert result["verdict"] == "reviewed"
    assert "reasoning-only" in result["notes"] or result["notes"]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failures = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((name, f"AssertionError: {exc}"))
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
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
    print("OK glm_critic_test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
