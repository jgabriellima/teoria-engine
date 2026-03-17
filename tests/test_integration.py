"""
Integration tests — hit individual services directly to verify internal contracts.
These test gateway ↔ vLLM communication, auth, rate limiting, and health checks.
"""

import httpx
import pytest


class TestGatewayHealth:
    def test_health_endpoint_no_auth(self, client, gateway_url):
        r = client.get(f"{gateway_url}/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["vllm"] is True

    def test_health_through_nginx(self, client, nginx_url):
        r = client.get(f"{nginx_url}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


class TestGatewayAuth:
    def test_missing_api_key_returns_401(self, client, gateway_url):
        r = client.post(f"{gateway_url}/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert r.status_code == 401
        assert r.json()["error"] == "unauthorized"

    def test_wrong_api_key_returns_401(self, client, gateway_url):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "wrong-key"},
        )
        assert r.status_code == 401

    def test_bearer_token_auth(self, client, gateway_url, api_key):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert r.status_code == 200

    def test_x_api_key_auth(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=authed_headers,
        )
        assert r.status_code == 200


class TestGatewayValidation:
    def test_max_tokens_exceeds_limit(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 999999,
            },
            headers=authed_headers,
        )
        assert r.status_code == 400
        assert "limit" in r.json()["error"]

    def test_max_tokens_within_limit(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 100,
            },
            headers=authed_headers,
        )
        assert r.status_code == 200


class TestGatewayChatCompletion:
    def test_non_streaming_response_structure(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers=authed_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "choices" in body
        assert len(body["choices"]) > 0
        assert "message" in body["choices"][0]
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert len(body["choices"][0]["message"]["content"]) > 0

    def test_streaming_response(self, gateway_url, authed_headers):
        with httpx.Client(timeout=30.0) as c:
            with c.stream(
                "POST",
                f"{gateway_url}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
                headers=authed_headers,
            ) as resp:
                assert resp.status_code == 200
                chunks = []
                for line in resp.iter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunks.append(line)
                assert len(chunks) > 0

    def test_simple_chat_endpoint(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/chat",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers=authed_headers,
        )
        assert r.status_code == 200
        assert "choices" in r.json()
