"""
Smoke tests — run against the REAL production stack (vLLM + GPU).

These tests validate actual model inference end-to-end.
NOT for CI/CD. Run manually on a GPU machine after `make up`.

Usage:
    make test-smoke              # against NGINX on port 80
    TEST_NGINX_URL=http://localhost:8081 make test-smoke  # custom port
"""

import json
import httpx
import pytest


TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class TestRealInference:
    """Validates that the model actually produces coherent output."""

    def test_basic_math(self, nginx_url, authed_headers):
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{nginx_url}/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "What is 2+2? Reply with just the number."}],
                "max_tokens": 16,
            }, headers=authed_headers)
        assert r.status_code == 200
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        assert "4" in content, f"Expected '4' in response, got: {content}"
        assert body["usage"]["completion_tokens"] > 0

    def test_follows_instruction(self, nginx_url, authed_headers):
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{nginx_url}/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "Say exactly: hello world"}],
                "max_tokens": 32,
            }, headers=authed_headers)
        assert r.status_code == 200
        content = r.json()["choices"][0]["message"]["content"].lower()
        assert "hello" in content and "world" in content, (
            f"Expected 'hello' and 'world' in: {content}"
        )

    def test_multi_turn_conversation(self, nginx_url, authed_headers):
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{nginx_url}/v1/chat/completions", json={
                "messages": [
                    {"role": "user", "content": "My name is Alice."},
                    {"role": "assistant", "content": "Nice to meet you, Alice!"},
                    {"role": "user", "content": "What is my name?"},
                ],
                "max_tokens": 32,
            }, headers=authed_headers)
        assert r.status_code == 200
        content = r.json()["choices"][0]["message"]["content"]
        assert "Alice" in content, f"Expected 'Alice' in: {content}"


class TestRealStreaming:
    """Validates that streaming produces real tokens incrementally."""

    def test_streaming_produces_real_tokens(self, nginx_url, authed_headers):
        collected = []
        with httpx.Client(timeout=TIMEOUT) as c:
            with c.stream("POST", f"{nginx_url}/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "Count from 1 to 5."}],
                "max_tokens": 64,
                "stream": True,
            }, headers=authed_headers) as resp:
                assert resp.status_code == 200
                for line in resp.iter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line.removeprefix("data: "))
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            collected.append(delta["content"])

        full = "".join(collected)
        assert len(collected) > 1, "Expected multiple streaming chunks"
        assert any(d in full for d in ["1", "2", "3"]), f"Expected numbers in: {full}"


class TestModelMetadata:
    """Validates vLLM is serving the expected model."""

    def test_model_name_in_response(self, nginx_url, authed_headers):
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{nginx_url}/v1/chat/completions", json={
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8,
            }, headers=authed_headers)
        assert r.status_code == 200
        model = r.json().get("model", "")
        assert len(model) > 0, "Response should include model name"


class TestGPUHealth:
    """Validates the stack is healthy with real GPU inference."""

    def test_health_with_real_backend(self, client, nginx_url):
        r = client.get(f"{nginx_url}/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["backend"] is True

    def test_concurrent_real_inference(self, nginx_url, authed_headers):
        """5 parallel requests to verify vLLM batching works."""
        import asyncio

        async def fire():
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                tasks = [
                    c.post(f"{nginx_url}/v1/chat/completions", json={
                        "messages": [{"role": "user", "content": f"Say the number {i}"}],
                        "max_tokens": 16,
                    }, headers=authed_headers)
                    for i in range(5)
                ]
                return await asyncio.gather(*tasks)

        results = asyncio.run(fire())
        for r in results:
            assert r.status_code == 200
            assert len(r.json()["choices"][0]["message"]["content"]) > 0
