"""
teoria-engine — OpenAI-compatible client example.

Drop-in replacement for the OpenAI Python SDK.
Set OPENAI_BASE_URL and OPENAI_API_KEY (or GATEWAY_API_KEY) before running.

Usage:
    export OPENAI_BASE_URL=http://localhost:9000/v1
    export OPENAI_API_KEY=<your-GATEWAY_API_KEY>
    python openai_client.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Iterator

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

# ── Client setup ──────────────────────────────────────────────────────────────
BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:9000/v1")
API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("GATEWAY_API_KEY", "default")
MODEL = os.getenv("TEORIA_MODEL", "auto")  # "auto" lets gateway pick active model

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


# ── Basic completion ───────────────────────────────────────────────────────────
def chat(
    messages: list[ChatCompletionMessageParam],
    *,
    model: str = MODEL,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """Single-turn chat completion. Returns the assistant message as a string."""
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


# ── Streaming completion ───────────────────────────────────────────────────────
def stream_chat(
    messages: list[ChatCompletionMessageParam],
    *,
    model: str = MODEL,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> Iterator[str]:
    """Streaming chat — yields text chunks as they arrive."""
    with client.chat.completions.stream(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    ) as stream:
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ── Tool / function calling ───────────────────────────────────────────────────
def chat_with_tools(
    messages: list[ChatCompletionMessageParam],
    tools: list[dict],
    *,
    model: str = MODEL,
    max_tokens: int = 1024,
) -> dict:
    """
    Single-turn tool call. Returns the raw response dict.
    Requires nemotron profile with enable_auto_tool_choice: true in engine.yml.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,  # type: ignore[arg-type]
        tool_choice="auto",
        max_tokens=max_tokens,
    )
    msg = resp.choices[0].message
    if msg.tool_calls:
        return {
            "tool_calls": [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in msg.tool_calls
            ]
        }
    return {"content": msg.content}


# ── Vision-language (qwen3-vl-8b profile) ────────────────────────────────────
def vision_chat(
    image_url: str,
    prompt: str,
    *,
    model: str = MODEL,
    max_tokens: int = 512,
) -> str:
    """
    Vision-language request. Pre-resize images to ≤768 px before calling.
    Requires qwen3-vl-8b profile. Hard limits: 1 image/request, max 2 concurrent.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


# ── Health check ──────────────────────────────────────────────────────────────
def health() -> dict:
    """Check gateway health. No auth required."""
    import urllib.request

    base = BASE_URL.rstrip("/v1").rstrip("/")
    with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
        return json.loads(r.read())


# ── Demo ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Base URL : {BASE_URL}")
    print(f"Model    : {MODEL}")
    print()

    # 1. Health check
    try:
        h = health()
        print(f"Health   : {h}")
    except Exception as e:
        print(f"Health check failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. List models
    models = client.models.list()
    print(f"Models   : {[m.id for m in models.data]}")
    print()

    # 3. Basic completion
    print("=== Basic completion ===")
    answer = chat(
        [{"role": "user", "content": "Explain vLLM in one sentence."}],
        temperature=0,
    )
    print(answer)
    print()

    # 4. Streaming
    print("=== Streaming ===")
    for chunk in stream_chat(
        [{"role": "user", "content": "Count from 1 to 5, one per line."}],
        max_tokens=64,
        temperature=0,
    ):
        print(chunk, end="", flush=True)
    print("\n")

    # 5. Tool calling (only with nemotron profile)
    print("=== Tool calling ===")
    result = chat_with_tools(
        messages=[{"role": "user", "content": "What's the weather in São Paulo?"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name",
                            }
                        },
                        "required": ["location"],
                    },
                },
            }
        ],
    )
    print(json.dumps(result, indent=2))
