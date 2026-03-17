import os
import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

VLLM_URL = os.getenv("VLLM_URL", "http://vllm:8000")
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
    _http = httpx.AsyncClient(base_url=VLLM_URL, timeout=httpx.Timeout(300.0, connect=10.0))
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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    if err := _validate_payload(payload):
        return JSONResponse({"error": err}, status_code=400)

    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            stream = payload.get("stream", False)
            if stream:
                return await _stream_response(payload)
            resp = await _http.post("/v1/chat/completions", json=payload)
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

    async with _semaphore:
        with tracer.start_as_current_span("llm_request"):
            resp = await _http.post("/v1/chat/completions", json=payload)
            return JSONResponse(resp.json(), status_code=resp.status_code)


@app.get("/health")
async def health():
    try:
        r = await _http.get("/health")
        vllm_ok = r.status_code == 200
    except Exception:
        vllm_ok = False
    status = "healthy" if vllm_ok else "degraded"
    code = 200 if vllm_ok else 503
    return JSONResponse({"status": status, "vllm": vllm_ok}, status_code=code)
