"""Optional: let Claude rewrite the highest-priority drafts so they read like a person.

Off by default. Templates are deterministic, free and auditable, which is what
you want for the long tail. For the handful of messages an AM will actually
send each day, `--llm N` rewrites the top N human/review drafts.

Guardrails: the model only rewrites wording. The prompt forbids new facts,
numbers, offers or links, and any failure (no key, no package, API error)
falls back to the template so the daily run never breaks.

Needs `pip install anthropic` and ANTHROPIC_API_KEY. Model override:
AUTOPILOT_LLM_MODEL (default claude-sonnet-5-5).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

SYSTEM = (
    "You edit B2B account-management messages for Fleek, a wholesale marketplace for secondhand and "
    "vintage clothing. Rewrite the draft so it sounds like a warm, concise account manager writing to "
    "a customer they know. Keep every fact, number, link and offer exactly as given; add none. "
    "Keep it under 120 words, British English, no emojis, no subject line. Return only the message."
)


def polish_top(df: pd.DataFrame, n: int) -> pd.DataFrame:
    if n <= 0:
        return df
    try:
        from anthropic import Anthropic
    except ImportError:
        print("  --llm skipped: `pip install anthropic` to enable", file=sys.stderr)
        return df
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  --llm skipped: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return df

    client = Anthropic()
    model = os.environ.get("AUTOPILOT_LLM_MODEL", "claude-sonnet-5-5")
    targets = df[df["owner"].isin(["human", "review"]) & df["draft_message"].ne("")]
    targets = targets.sort_values("priority", ascending=False).head(n)
    polished = 0
    for idx, row in targets.iterrows():
        prompt = (f"Context for you only (do not quote it): {row['why']}\n\n"
                  f"Draft to rewrite:\n{row['draft_message']}")
        try:
            msg = client.messages.create(model=model, max_tokens=600, system=SYSTEM,
                                         messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            if text:
                df.at[idx, "draft_message"] = text
                polished += 1
        except Exception as exc:  # keep the template on any failure
            print(f"  --llm kept template for {row['account_id']}: {exc}", file=sys.stderr)
    print(f"  --llm polished {polished} drafts with {model}", file=sys.stderr)
    return df
