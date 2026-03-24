# teoria-engine — Technical Reference

## Architecture overview

```
Internet / Agent
      │
  Cloudflare Tunnel (optional)
      │
  NGINX :80          ← rate limiting, reverse proxy
      │
  Gateway :9000      ← FastAPI, auth, caching, concurrency, OTLP traces
      │
  ┌───┴───────────────────┐
  │                       │
vLLM :8000           MLX server :8000
(Linux NVIDIA)       (macOS Apple Silicon)
```

The gateway always speaks OpenAI-compatible HTTP to the backend regardless of which it is.
On macOS the gateway container reaches the MLX server via `host.docker.internal`.

---

## API Reference

### Authentication

All endpoints except `/health`, `/docs`, and `/openapi.json` require one of:

```
x-api-key: <GATEWAY_API_KEY>
Authorization: Bearer <GATEWAY_API_KEY>
```

### Endpoints

#### `GET /health`

No authentication required. Returns backend health and the resolved backend URL.

```json
{"status": "ok", "backend": "vllm", "backend_url": "http://vllm:8000"}
```

Returns HTTP 503 if the backend is unreachable.

#### `GET /v1/models`

Returns model list from backend. Standard OpenAI format.

#### `POST /v1/chat/completions`

Full OpenAI-compatible chat completions proxy. Model field is optional — gateway injects
the active model when omitted.

**Request:**

```json
{
  "model": "auto",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"}
  ],
  "max_tokens": 512,
  "temperature": 0.7,
  "stream": false,
  "tools": [],
  "tool_choice": "auto"
}
```

**Response (non-streaming):**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello! How can I help?"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21}
}
```

**Streaming:** Server-Sent Events (SSE) format, `Content-Type: text/event-stream`.
Compatible with `stream=True` in the OpenAI Python SDK.

**Caching:** When `temperature == 0`, responses are cached (TTL: 3600 s default).
Cache hit returns instantly, even as a synthesized SSE stream.

**Concurrency:** Enforced by `MAX_CONCURRENT_REQUESTS` semaphore. Excess requests
receive HTTP 429.

#### `POST /api/v1/chat`

Simplified task-oriented API. Returns OpenAI-compatible response.

**Request:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `input` | string | yes | — | User prompt |
| `system_prompt` | string | no | — | System instruction |
| `model` | string | no | — | Model ID (uses server default) |
| `temperature` | float | no | 0.7 | 0–2 |
| `max_tokens` | int | no | 2048 | Max completion tokens |
| `stream` | boolean | no | false | Stream response |

#### `POST /chat`

Alias for chat completions (non-streaming path). Same request/response as `/v1/chat/completions`.

---

## Configuration reference

### `.env` — secrets and hardware

```bash
# Required
GATEWAY_API_KEY=<strong-random-key>          # auth key for all gateway requests
HUGGINGFACE_TOKEN=hf_...                     # needed to download gated models

# Hardware (Linux only)
VLLM_GPU_DEVICE=0                            # GPU device index (0-based)

# Optional overrides
GATEWAY_PORT=9000                            # host port for the gateway
```

### `config/engine.yml` — model profiles and stack config

```yaml
# Active model profile (switch with: teoria-engine config --model <name>)
active_model: nemotron

models:
  <profile-name>:
    # vLLM backend (Linux + NVIDIA)
    hf_name: <huggingface-model-id>

    # MLX backend (macOS Apple Silicon)
    mlx_name: <huggingface-model-id>

    # vLLM serving flags
    trust_remote_code: false         # --trust-remote-code
    max_model_len: 131072            # max context length
    gpu_memory_utilization: 0.95     # fraction of VRAM for KV cache
    max_num_seqs: 256                # max concurrent sequences
    max_num_batched_tokens: 8192     # max tokens per batch
    prefix_caching: true             # --enable-prefix-caching
    chunked_prefill: true            # --enable-chunked-prefill
    enforce_eager: false             # --enforce-eager (required for VL stability)
    async_scheduling: false          # --async-scheduling

    # Tool / function calling
    enable_auto_tool_choice: false
    tool_call_parser: llama3_json    # llama3_json | mistral | hermes | internlm | granite-20b-fc

    # Pass raw args to `vllm serve` (not covered above)
    vllm_extra_args: ""

    # Per-model gateway overrides (override global gateway: block below)
    gateway:
      max_input_tokens: 8000
      max_output_tokens: 2000
      max_concurrent_requests: 64
      cache:
        enabled: true
        max_entries: 2048
        ttl_seconds: 3600

# MLX server (macOS only)
mlx:
  port: 8000
  host: "0.0.0.0"

# Global gateway defaults (overridden per-model in model.gateway: block)
gateway:
  port: 9000
  max_input_tokens: 8000
  max_output_tokens: 2000
  max_concurrent_requests: 64
  cache:
    enabled: true
    max_entries: 2048
    ttl_seconds: 3600        # only applied when temperature == 0

# NGINX
nginx:
  rate_limit: "5r/s"
  burst: 20

# Observability
observability:
  otel_endpoint: "http://otel-collector:4317"
  service_name: "teoria-engine"

# Cloudflare tunnel (optional)
tunnel:
  id: <your-tunnel-id>
  name: <tunnel-name>
  hostname: <your-domain.example.com>
```

---

## Model profiles

### nemotron (default)

| Setting | Value |
|---|---|
| vLLM | `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` |
| MLX | `mlx-community/Mistral-NeMo-Minitron-8B-Instruct-4bit` |
| Context | 131 072 tokens |
| Tool calling | yes (`llama3_json` parser) |
| VRAM (vLLM) | ~16 GB |
| Best for | Text generation, tool/function calling, agentic tasks |

### qwen-0.5b

| Setting | Value |
|---|---|
| vLLM | `Qwen/Qwen2.5-0.5B-Instruct` |
| MLX | `mlx-community/Qwen2.5-0.5B-Instruct-4bit` |
| Context | 4 096 tokens |
| Tool calling | no |
| VRAM (vLLM) | ~4 GB |
| Best for | Fast/lightweight inference, low-VRAM machines |

### qwen3-vl-8b

| Setting | Value |
|---|---|
| vLLM | `unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit` |
| MLX | `mlx-community/Qwen3-VL-8B-Instruct-4bit` |
| Context | 4 096 tokens |
| Tool calling | no |
| VRAM (vLLM) | ~24 GB |
| Best for | Vision-language: image captioning, OCR, VQA |
| Hard limits | 1 image/request, ≤768 px, max 2 concurrent requests |

---

## Environment variables (gateway container)

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | — | Must match `GATEWAY_API_KEY` in `.env` |
| `VLLM_URL` | `http://vllm:8000` | Backend base URL (auto-set to MLX host on macOS) |
| `VLLM_MODEL` | — | Forces model field on all proxied requests |
| `MAX_OUTPUT_TOKENS` | 2000 | Hard cap on completion tokens |
| `MAX_CONCURRENT_REQUESTS` | 64 | Semaphore limit |
| `CACHE_ENABLED` | true | Enable response cache |
| `CACHE_MAX_ENTRIES` | 2048 | LRU cache size |
| `CACHE_TTL_SECONDS` | 3600 | Cache TTL (temp=0 requests only) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | If set, enables OTLP gRPC trace export |

---

## Docker Compose profiles

| Profile | Activates | When |
|---|---|---|
| *(default)* | gateway, nginx, openobserve, otel-collector | always |
| `gpu` | vllm | Linux + NVIDIA only |
| `tunnel` | cloudflared | when `cloudflared/tunnel.json` exists |
| `disabled` | — | test mode (disables otel-collector) |

---

## Observability

The gateway is instrumented with OpenTelemetry (`FastAPIInstrumentor`).

Configure the downstream backend in `otel/otel-collector-config.yml`.
Default: export to OpenObserve on `http://openobserve:5081`.

Access OpenObserve UI at `http://localhost:5080` (default credentials in `.env`).

Key metrics to monitor:
- `tokens/sec`, `TTFT` (time-to-first-token), `TPOT` (time-per-output-token)
- GPU utilization and VRAM (`nvidia-smi dmon`)
- Request latency and queue depth (OTLP spans)
- KV cache hit rate (vLLM admin endpoint)

---

## Tool / function calling

Enabled per model profile:

```yaml
enable_auto_tool_choice: true
tool_call_parser: llama3_json   # or: mistral | hermes | internlm | granite-20b-fc
```

Standard OpenAI tools format in requests:

```json
{
  "messages": [...],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get current weather",
      "parameters": {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"]
      }
    }
  }],
  "tool_choice": "auto"
}
```

---

## Cloudflare tunnel

The tunnel (`cloudflared` profile) exposes the NGINX port 80 to the internet without
opening firewall ports. The hostname is configured in `config/engine.yml → tunnel.hostname`.

Setup (one-time, run locally):

```bash
bin/setup-tunnel
```

Then copy `cloudflared/tunnel.json` securely to the production VM.
The tunnel starts automatically when `cloudflared/tunnel.json` is present and `teoria-engine up` runs.

---

## CLI reference

```
teoria-engine up                         start all services
teoria-engine down                       stop all services
teoria-engine restart                    restart all services
teoria-engine logs [N]                   follow logs (last N lines)
teoria-engine status                     container + backend status
teoria-engine health                     gateway + LLM backend health
teoria-engine config [--model <name>]    show or switch model profile
teoria-engine preflight                  verify system prerequisites

# Linux only (requires root)
teoria-engine service                    install systemd service
teoria-engine unservice                  remove systemd service
```

All commands available via `make` as well: `make up`, `make down`, `make health`, etc.
