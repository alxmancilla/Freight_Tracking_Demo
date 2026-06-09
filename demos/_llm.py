"""Optional LLM helper.

Returns the model response, or a '[skipped: <reason>]' string when no
provider is configured. Never raises on missing config; raises only for
real API errors so they surface during the demo.

Activate by setting one of:
  - ANTHROPIC_API_KEY  (and: pip install anthropic)
  - OPENAI_API_KEY     (and: pip install openai)

Override the model with LLM_MODEL (defaults: claude-sonnet-4-5 / gpt-4o-mini).
"""
import os


def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
        except ImportError:
            return "[skipped: ANTHROPIC_API_KEY set but `pip install anthropic` first]"
        model = os.getenv("LLM_MODEL") or "claude-sonnet-4-5"
        msg = anthropic.Anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return f"[{model}] " + msg.content[0].text

    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
        except ImportError:
            return "[skipped: OPENAI_API_KEY set but `pip install openai` first]"
        model = os.getenv("LLM_MODEL") or "gpt-4o-mini"
        resp = OpenAI().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return f"[{model}] " + (resp.choices[0].message.content or "(empty)")

    return "[skipped: set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable LLM call]"
