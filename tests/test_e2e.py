"""
End-to-end tests — hit the public NGINX endpoint exactly as a real client would.
Full path: client → NGINX → gateway (auth + validation) → vLLM → response.
"""

import json
import httpx
import pytest


class TestE2EFullStack:
    """Tests that traverse the entire stack via NGINX."""

    def test_chat_completion_through_nginx(self, client, nginx_url, authed_headers):
        r = client.post(
            f"{nginx_url}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "max_tokens": 100,
            },
            headers=authed_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["choices"][0]["message"]["content"]
        assert body["usage"]["total_tokens"] > 0

    def test_streaming_through_nginx(self, nginx_url, authed_headers):
        collected = []
        with httpx.Client(timeout=30.0) as c:
            with c.stream(
                "POST",
                f"{nginx_url}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Count to 3"}],
                    "stream": True,
                },
                headers=authed_headers,
            ) as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")
                for line in resp.iter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line.removeprefix("data: "))
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            collected.append(delta["content"])
        full_response = "".join(collected)
        assert len(full_response) > 0

    def test_auth_enforced_through_nginx(self, client, nginx_url):
        r = client.post(
            f"{nginx_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 401

    def test_wrong_key_through_nginx(self, client, nginx_url):
        r = client.post(
            f"{nginx_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "bad-key"},
        )
        assert r.status_code == 401

    def test_max_tokens_rejected_through_nginx(self, client, nginx_url, authed_headers):
        r = client.post(
            f"{nginx_url}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 999999,
            },
            headers=authed_headers,
        )
        assert r.status_code == 400

    def test_health_publicly_accessible(self, client, nginx_url):
        r = client.get(f"{nginx_url}/health")
        assert r.status_code == 200
        assert r.json()["vllm"] is True


class TestE2EMultipleRequests:
    """Verify the stack handles concurrent-ish load."""

    def test_sequential_requests(self, client, nginx_url, authed_headers):
        for i in range(5):
            r = client.post(
                f"{nginx_url}/v1/chat/completions",
                json={"messages": [{"role": "user", "content": f"request {i}"}]},
                headers=authed_headers,
            )
            assert r.status_code == 200
            assert "choices" in r.json()

    def test_concurrent_requests(self, nginx_url, authed_headers):
        import asyncio

        async def fire():
            async with httpx.AsyncClient(timeout=30.0) as c:
                tasks = [
                    c.post(
                        f"{nginx_url}/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": f"concurrent {i}"}]},
                        headers=authed_headers,
                    )
                    for i in range(10)
                ]
                results = await asyncio.gather(*tasks)
            return results

        results = asyncio.run(fire())
        for r in results:
            assert r.status_code == 200
            assert "choices" in r.json()
