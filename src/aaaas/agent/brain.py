"""The agent brain: a ReAct loop over the tool registry.

The brain talks to an ``LLMClient`` — an abstraction with two
implementations: ``AnthropicLLM`` (a real Claude model via the SDK) and
``FakeLLM`` (a scripted client for deterministic tests and offline demos).
The loop is the classic Reason -> Act -> Observe cycle: the model emits
tool calls, the brain executes them through the registry, feeds the results
back, and repeats until the model stops.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .prompts import SYSTEM_PROMPT

if TYPE_CHECKING:  # avoid an import cycle: tools import the agent package
    from ..tools.base import ToolRegistry


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "tool_use" while the model wants tools


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        ...


@dataclass
class Step:
    tool: str
    input: dict
    result: dict


@dataclass
class RunResult:
    done: bool
    final: str
    steps: list[Step] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Real Claude brain
# --------------------------------------------------------------------------- #
class AnthropicLLM:
    """Drives the loop with a real Claude model. Requires the ``anthropic`` SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6", max_tokens: int = 1024):
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "AnthropicLLM needs the 'anthropic' package: pip install anthropic"
            ) from exc
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in resp.content if getattr(b, "type", None) == "tool_use"
        ]
        return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=resp.stop_reason)


# --------------------------------------------------------------------------- #
# Scripted brain for tests / offline demos
# --------------------------------------------------------------------------- #
class FakeLLM:
    """Replays a fixed script of ``LLMResponse`` objects.

    Lets the entire agent loop — including tool execution and HITL gating —
    run with no API key. Records the message history it was handed for asserts.
    """

    def __init__(self, script: list[LLMResponse]):
        self._script = list(script)
        self.calls: list[list[dict]] = []

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        if self._script:
            return self._script.pop(0)
        return LLMResponse(text="Done.", tool_calls=[], stop_reason="end_turn")


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
class Agent:
    def __init__(
        self,
        llm: LLMClient,
        registry: "ToolRegistry",
        system_prompt: str = SYSTEM_PROMPT,
        max_steps: int = 10,
    ):
        self.llm = llm
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    def run(self, task: str) -> RunResult:
        messages: list[dict] = [{"role": "user", "content": task}]
        steps: list[Step] = []
        schemas = self.registry.to_anthropic_schemas()

        for _ in range(self.max_steps):
            resp = self.llm.complete(self.system_prompt, messages, schemas)

            if resp.stop_reason != "tool_use" and not resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.text})
                return RunResult(True, resp.text or "Done.", steps, messages)

            # Record the assistant turn (text + tool_use blocks).
            assistant_content: list[dict] = []
            if resp.text:
                assistant_content.append({"type": "text", "text": resp.text})
            for tc in resp.tool_calls:
                assistant_content.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each requested tool and feed results back.
            tool_results: list[dict] = []
            for tc in resp.tool_calls:
                payload = self._execute(tc)
                steps.append(Step(tool=tc.name, input=tc.input, result=payload))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(payload),
                })
            messages.append({"role": "user", "content": tool_results})

        return RunResult(False, "Stopped: reached max reasoning steps.", steps, messages)

    def _execute(self, tc: ToolCall) -> dict:
        tool = self.registry.get(tc.name)
        if tool is None:
            return {"ok": False, "action": tc.name, "message": f"Unknown tool {tc.name!r}."}
        try:
            result = tool.func(**tc.input)
            return result.to_payload()
        except TypeError as exc:
            return {"ok": False, "action": tc.name, "message": f"Bad arguments: {exc}"}
        except Exception as exc:  # fail loud, never silently swallow
            return {"ok": False, "action": tc.name, "message": f"Tool error: {exc}"}
