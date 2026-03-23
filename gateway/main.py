import os
import asyncio
from contextlib import asynccontextmanager
import httpx
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

_semaphore: asyncio.Semaphore
_http: httpx.AsyncClient
tracer = trace.get_tracer(__name__)


def _init_telemetry() -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _semaphore, _http
    _init_telemetry()
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    _http = httpx.AsyncClient(base_url=LLM_BACKEND_URL, timeout=httpx.Timeout(300.0, connect=10.0))
    yield
    await _http.aclose()


app = FastAPI(title="teoria-engine gateway", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path in ("/health", "/docs", "/openapi.json"):
        return await call_next(request)
    key = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if key != API_KEY:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
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
        return JSONResponse({"error": err}, status_code=400)

    llm_payload = _chat_request_to_openai(payload)

    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            if payload.stream:
                return await _stream_response(llm_payload)
            resp = await _http.post("/v1/chat/completions", json=llm_payload)
            return JSONResponse(resp.json(), status_code=resp.status_code)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    if err := _validate_payload(payload):
        return JSONResponse({"error": err}, status_code=400)

    llm_payload = _resolve_model(payload)
    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            stream = llm_payload.get("stream", False)
            if stream:
                return await _stream_response(llm_payload)
            resp = await _http.post("/v1/chat/completions", json=llm_payload)
            return JSONResponse(resp.json(), status_code=resp.status_code)


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


@app.post("/chat")
async def chat_simple(request: Request):
    """Convenience alias matching the architecture doc."""
    payload = await request.json()
    if err := _validate_payload(payload):
        return JSONResponse({"error": err}, status_code=400)

    llm_payload = _resolve_model(payload)
    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            resp = await _http.post("/v1/chat/completions", json=llm_payload)
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
