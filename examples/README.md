# Examples

Runnable, no API key or Odoo required.

| Script | Shows |
|---|---|
| `../src/aaaas/cli.py` (`python -m aaaas.cli`) | The full bookkeeping walkthrough: matching, escalation, aging, reconciliation, hard-HITL posting, daily summary, audit trail. Try `--personality genz`. |
| `demo_agent_react.py` | The agent's Reason→Act→Observe loop driving the tools via a scripted brain, with live confidence gating. |

```bash
# from the repo root
python -m aaaas.cli
python examples/demo_agent_react.py
```

Swap the scripted `FakeLLM` for `AnthropicLLM` (set `AAAAS_ANTHROPIC_API_KEY`)
to let a real Claude model choose the steps.
