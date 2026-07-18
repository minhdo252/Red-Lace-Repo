"""Smoke test for the three-stage orchestrator. Drives handle_turn with a
fake ai_client / call_tool / read_image / critic_pass so it exercises the
loop logic without the Qdrant/Postgres stack or a live model."""

import asyncio
import base64

import app.agent.orchestrator as orch


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
    """Returns queued responses in order, one per chat() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        return self._responses.pop(0)


def test_plain_text_turn_no_tools_no_critic():
    orch.ai_client = _ScriptedClient([_FakeResponse(content="Xin chao!")])
    result = asyncio.run(orch.handle_turn("hello"))
    assert result["reply"] == "Xin chao!", result
    assert result["tools_invoked"] == [], result
    assert "critic" not in result, result


def test_image_notes_injected_before_loop():
    async def fake_read_image(image_bytes, mode, region=None, category="food"):
        return {"mode": mode, "text": "MENU: pho 40k"}

    client = _ScriptedClient([_FakeResponse(content="done")])
    orch.read_image = fake_read_image
    orch.ai_client = client

    img = {"image_base64": base64.b64encode(b"x").decode(), "mode": "dish"}
    asyncio.run(orch.handle_turn("what is this", images=[img]))

    # The first chat() call must already contain the read_image note as a user message.
    first_messages = client.calls[0]
    assert any("read_image mode=dish" in str(m.get("content")) for m in first_messages), first_messages


def test_risk_flag_triggers_critic():
    async def fake_call_tool(name, arguments):
        return {"flag": "cao hon gia tham chieu 80%"}

    async def fake_critic_pass(conclusion, evidence):
        return {"notes": "reviewed"}

    responses = [
        _FakeResponse(
            tool_calls=[
                _FakeCall("c1", "compare_price", {"item": "pho", "region": "Hanoi", "observed_price": 90000})
            ]
        ),
        _FakeResponse(content="Gia nay cao hon binh thuong."),
    ]
    orch.ai_client = _ScriptedClient(responses)
    orch.call_tool = fake_call_tool
    orch.critic_pass = fake_critic_pass

    result = asyncio.run(orch.handle_turn("is 90k for pho fair?"))
    assert result["critic"] == {"notes": "reviewed"}, result
    assert result["tools_invoked"][0]["tool"] == "compare_price", result


if __name__ == "__main__":
    test_plain_text_turn_no_tools_no_critic()
    test_image_notes_injected_before_loop()
    test_risk_flag_triggers_critic()
    print("OK orchestrator_rewrite_test")
