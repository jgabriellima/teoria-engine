import os
import asyncio
import hashlib
import json
import threading
import time
from contextlib import asynccontextmanager

import httpx
from cachetools import TTLCache
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

LLM_BACKEND_URL = os.getenv("VLLM_URL", "http://vllm:8000")
LLM_MODEL = os.getenv("VLLM_MODEL", "")
API_KEY = os.getenv("API_KEY", "CHANGE_ME")
MAX_INPUT_TOKENS = int(os.getenv("MAX_INPUT_TOKENS", "8000"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2000"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_REQUESTS", "64"))

CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "2048"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

_semaphore: asyncio.Semaphore
_http: httpx.AsyncClient
_cache: TTLCache
_cache_lock: threading.Lock
tracer = trace.get_tracer(__name__)

_CACHE_KEY_FIELDS = ("messages", "model", "max_tokens", "temperature", "top_p", "stop")


def _init_telemetry() -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _semaphore, _http, _cache, _cache_lock
    _init_telemetry()
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    _http = httpx.AsyncClient(base_url=LLM_BACKEND_URL, timeout=httpx.Timeout(300.0, connect=10.0))
    _cache = TTLCache(maxsize=CACHE_MAX_ENTRIES, ttl=CACHE_TTL)
    _cache_lock = threading.Lock()
    yield
    await _http.aclose()


app = FastAPI(title="teoria-engine gateway", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


def _openai_error(
    message: str,
    *,
    type_: str = "invalid_request_error",
    code: str | None = None,
    status: int = 400,
) -> JSONResponse:
    """Return an OpenAI-shaped error envelope so SDK/LangChain error parsers work."""
    return JSONResponse(
        {"error": {"message": message, "type": type_, "code": code}},
        status_code=status,
    )


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path in ("/health", "/docs", "/openapi.json"):
        return await call_next(request)
    key = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if key != API_KEY:
        return _openai_error("Invalid API key.", type_="authentication_error", code="invalid_api_key", status=401)
    return await call_next(request)


def _validate_payload(payload: dict) -> str | None:
    max_tokens = payload.get("max_tokens") or payload.get("max_completion_tokens")
    if max_tokens and int(max_tokens) > MAX_OUTPUT_TOKENS:
        return f"max_tokens exceeds limit of {MAX_OUTPUT_TOKENS}"
    return None


def _resolve_model(payload: dict) -> dict:
    """Rewrite model field so the backend receives the correct model ID."""
    out = dict(payload)
    out["model"] = LLM_MODEL or payload.get("model") or ""
    return out


def _cache_key(payload: dict) -> str:
    """SHA-256 of the normalized payload fields that affect LLM output."""
    canonical = {k: payload.get(k) for k in _CACHE_KEY_FIELDS if payload.get(k) is not None}
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_deterministic(payload: dict) -> bool:
    return float(payload.get("temperature", 1.0)) == 0


def _cache_get(key: str) -> dict | None:
    if not CACHE_ENABLED:
        return None
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: str, value: dict) -> None:
    if not CACHE_ENABLED:
        return
    with _cache_lock:
        _cache[key] = value


class ChatRequest(BaseModel):
    """Simplified chat contract: system_prompt + input."""

    input: str = Field(..., min_length=1, description="User input / prompt")
    model: str | None = Field(None, description="Model ID (optional, uses server default)")
    system_prompt: str | None = Field(None, description="System instruction")
    temperature: float = Field(0.7, ge=0, le=2, description="Sampling temperature")
    max_tokens: int = Field(
        min(2048, MAX_OUTPUT_TOKENS), ge=1, le=MAX_OUTPUT_TOKENS, description="Max completion tokens"
    )
    stream: bool = Field(False, description="Stream response")


def _chat_request_to_openai(payload: ChatRequest) -> dict:
    """Transform simplified contract to OpenAI/vLLM format."""
    messages = []
    if payload.system_prompt:
        messages.append({"role": "system", "content": payload.system_prompt})
    messages.append({"role": "user", "content": payload.input})

    body: dict = {
        "messages": messages,
        "max_tokens": payload.max_tokens,
        "temperature": payload.temperature,
        "stream": payload.stream,
    }
    body["model"] = LLM_MODEL or payload.model or ""
    return body


@app.post("/api/v1/chat")
async def api_chat(payload: ChatRequest):
    """
    Simplified chat API: system_prompt + input.
    Proxies to vLLM OpenAI-compatible endpoint.
    """
    if err := _validate_payload(payload.model_dump()):
        return _openai_error(err)

    llm_payload = _chat_request_to_openai(payload)

    if _is_deterministic(llm_payload):
        key = _cache_key(llm_payload)
        cached = _cache_get(key)
        if cached is not None:
            return _stream_from_cache(cached) if payload.stream else JSONResponse(cached, headers={"X-Cache": "HIT"})
    else:
        key = None

    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            if payload.stream:
                return await _stream_response(llm_payload)
            resp = await _http.post("/v1/chat/completions", json=llm_payload)
            body = resp.json()
            if key is not None and resp.status_code == 200:
                _cache_put(key, body)
            return JSONResponse(body, status_code=resp.status_code, headers={"X-Cache": "MISS"} if key is not None else {})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    if err := _validate_payload(payload):
        return _openai_error(err)

    llm_payload = _resolve_model(payload)
    is_stream = llm_payload.get("stream", False)

    if _is_deterministic(llm_payload):
        key = _cache_key(llm_payload)
        cached = _cache_get(key)
        if cached is not None:
            return _stream_from_cache(cached) if is_stream else JSONResponse(cached, headers={"X-Cache": "HIT"})
    else:
        key = None

    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            if is_stream:
                return await _stream_response(llm_payload)
            resp = await _http.post("/v1/chat/completions", json=llm_payload)
            body = resp.json()
            if key is not None and resp.status_code == 200:
                _cache_put(key, body)
            return JSONResponse(body, status_code=resp.status_code, headers={"X-Cache": "MISS"} if key is not None else {})


async def _stream_response(payload: dict) -> StreamingResponse:
    req = _http.build_request("POST", "/v1/chat/completions", json=payload)
    resp = await _http.send(req, stream=True)

    async def generate():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})


def _stream_from_cache(cached: dict) -> StreamingResponse:
    """Reconstruct a valid SSE stream from a cached non-stream response.

    Cache is always written by non-stream requests. Streaming clients can read
    those entries — they get the full content in a single SSE chunk, which is
    spec-compliant and avoids a round-trip to the backend.
    """
    choice = cached.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    resp_id = cached.get("id", f"chatcmpl-cached-{int(time.time())}")
    created = cached.get("created", int(time.time()))
    model = cached.get("model", "")

    content_chunk = json.dumps({
        "id": resp_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}],
    })
    finish_chunk = json.dumps({
        "id": resp_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })

    async def generate():
        yield f"data: {content_chunk}\n\n"
        yield f"data: {finish_chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "X-Cache": "HIT"},
    )


@app.post("/chat")
async def chat_simple(request: Request):
    """Convenience alias matching the architecture doc."""
    payload = await request.json()
    if err := _validate_payload(payload):
        return _openai_error(err)

    llm_payload = _resolve_model(payload)

    if _is_deterministic(llm_payload):
        key = _cache_key(llm_payload)
        cached = _cache_get(key)
        if cached is not None:
            return JSONResponse(cached, headers={"X-Cache": "HIT"})
    else:
        key = None

    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            resp = await _http.post("/v1/chat/completions", json=llm_payload)
            body = resp.json()
            if key is not None and resp.status_code == 200:
                _cache_put(key, body)
            return JSONResponse(body, status_code=resp.status_code, headers={"X-Cache": "MISS"} if key is not None else {})


@app.get("/v1/models")
async def list_models():
    """Proxy GET /v1/models to the backend so OpenAI SDK and LangChain model-list calls work."""
    resp = await _http.get("/v1/models")
    return JSONResponse(resp.json(), status_code=resp.status_code)


@app.get("/health")
async def health():
    backend_ok = False
    try:
        r = await _http.get("/health")
        if r.status_code == 200:
            backend_ok = True
    except Exception:
        pass
    if not backend_ok:
        try:
            r = await _http.get("/v1/models")
            if r.status_code == 200:
                backend_ok = True
        except Exception:
            pass
    status = "healthy" if backend_ok else "degraded"
    code = 200 if backend_ok else 503
    return JSONResponse({"status": status, "backend": backend_ok, "backend_url": LLM_BACKEND_URL}, status_code=code)
