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
        assert body["backend"] is True

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
        err = r.json()["error"]
        assert err["type"] == "authentication_error"
        assert err["code"] == "invalid_api_key"

    def test_wrong_api_key_returns_401(self, client, gateway_url):
        r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"x-api-key": "wrong-key"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["type"] == "authentication_error"

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


class TestGatewayModels:
    def test_list_models_returns_200(self, client, gateway_url, authed_headers):
        r = client.get(f"{gateway_url}/v1/models", headers=authed_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["object"] == "list"
        assert len(body["data"]) > 0

    def test_model_id_matches_chat_completions(self, client, gateway_url, authed_headers):
        r = client.get(f"{gateway_url}/v1/models", headers=authed_headers)
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()["data"]]
        chat_r = client.post(
            f"{gateway_url}/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 8},
            headers=authed_headers,
        )
        assert chat_r.status_code == 200
        response_model = chat_r.json().get("model", "")
        assert response_model in ids, f"model '{response_model}' not in /v1/models: {ids}"

    def test_list_models_requires_auth(self, client, gateway_url):
        r = client.get(f"{gateway_url}/v1/models")
        assert r.status_code == 401


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
        err = r.json()["error"]
        assert err["type"] == "invalid_request_error"
        assert "limit" in err["message"]

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


class TestApiV1Chat:
    """Simplified contract: system_prompt + input."""

    def test_basic_input(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/api/v1/chat",
            json={"input": "What is 2+2? Reply with just the number."},
            headers=authed_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "choices" in body
        assert len(body["choices"][0]["message"]["content"]) > 0

    def test_system_prompt_and_input(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/api/v1/chat",
            json={
                "input": "Compute exactly: 2 + 2",
                "system_prompt": "Compute the exact result. Show reasoning and then provide the final integer.",
                "temperature": 0,
                "max_tokens": 64,
            },
            headers=authed_headers,
        )
        assert r.status_code == 200
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        assert "4" in content or "four" in content.lower()

    def test_requires_auth(self, client, gateway_url):
        r = client.post(
            f"{gateway_url}/api/v1/chat",
            json={"input": "hi"},
        )
        assert r.status_code == 401

    def test_empty_input_rejected(self, client, gateway_url, authed_headers):
        r = client.post(
            f"{gateway_url}/api/v1/chat",
            json={"input": ""},
            headers=authed_headers,
        )
        assert r.status_code == 422
