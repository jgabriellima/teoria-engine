import os
import pytest
import httpx

NGINX_URL = os.getenv("TEST_NGINX_URL", "http://localhost:80")
GATEWAY_URL = os.getenv("TEST_GATEWAY_URL", "http://localhost:9000")
API_KEY = os.getenv("TEST_API_KEY", os.getenv("GATEWAY_API_KEY", "test-key-123"))


@pytest.fixture(scope="session")
def api_key():
    return API_KEY


@pytest.fixture(scope="session")
def nginx_url():
    return NGINX_URL


@pytest.fixture(scope="session")
def gateway_url():
    return GATEWAY_URL


@pytest.fixture(scope="session")
def authed_headers():
    return {"x-api-key": API_KEY, "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def client():
    return httpx.Client(timeout=30.0)
