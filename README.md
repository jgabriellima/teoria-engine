# teoria-engine

Production-grade LLM inference stack for single GPU nodes. Orchestrates vLLM, a FastAPI gateway, NGINX reverse proxy, and optional Cloudflare tunnel — all managed through a single CLI.

Default model: **nvidia/nemotron-3-nano-4b** (~31.6B params, ~3.6B active per token via MoE).

## Architecture

```
Internet
   │
Cloudflare Tunnel (optional)
   │
NGINX  ──  rate limiting, streaming
   │
Gateway (FastAPI)  ──  auth, concurrency control, telemetry
   │
vLLM  ──  continuous batching, PagedAttention, prefix caching
   │
GPU
```

Five Docker Compose services: `vllm`, `gateway`, `nginx`, `cloudflared` (opt-in profile), `otel-collector`.

## Requirements

| Component | Minimum |
|---|---|
| GPU | RTX 4090 / RTX 6000 / A100 (24 GB+ VRAM) |
| RAM | 64 GB |
| Disk | NVMe SSD |
| OS | Ubuntu 22.04 |
| CUDA | 12.4+ |
| Docker | Docker Engine + Compose plugin |
| Runtime | NVIDIA Container Toolkit |

## Quick Start

**One-line install:**

```bash
curl -sSL https://raw.githubusercontent.com/jambu/teoria-llm-engine/main/scripts/install.sh | bash
```

Or with options:

```bash
curl -sSL ... | bash -s -- --install-dir /opt/teoria-engine --service
```

**Manual setup:**

```bash
git clone https://github.com/jambu/teoria-llm-engine.git
cd teoria-llm-engine

cp .env.example .env          # set GATEWAY_API_KEY and HUGGINGFACE_TOKEN
teoria-engine preflight        # verify GPU, docker, nvidia runtime
teoria-engine up               # start everything
teoria-engine health           # confirm it's running
```

## Configuration

All application config lives in `config/engine.yml`. Secrets and hardware-specific values go in `.env`.

### .env (secrets only)

```
GATEWAY_API_KEY=your-secure-key
HUGGINGFACE_TOKEN=hf_...
VLLM_GPU_DEVICE=0
```

### config/engine.yml (model profiles)

```yaml
active_model: nemotron

models:
  nemotron:
    hf_name: nvidia/nemotron-3-nano-4b
    max_model_len: 131072
    gpu_memory_utilization: 0.95
    max_num_seqs: 256
    max_num_batched_tokens: 8192
    prefix_caching: true
    chunked_prefill: true

  qwen-0.5b:  # lightweight test/validation profile
    hf_name: Qwen/Qwen2.5-0.5B-Instruct
    max_model_len: 4096
    gpu_memory_utilization: 0.50
    ...
```

Switch models without editing files:

```bash
teoria-engine config --model qwen-0.5b
```

## CLI Reference

```
teoria-engine <command>

up                    Start all services
down                  Stop all services
restart               Restart all services
logs [N]              Follow logs (last N lines, default 200)
status                Show container status
health                Check gateway health
config [--model X]    Show resolved configuration
service               Install as systemd service (requires root)
unservice             Remove systemd service (requires root)
preflight             Check system prerequisites
help                  Show help
```

All commands are also available via `make`:

```
make up            make down          make restart
make logs          make status        make health
make preflight     make service       make build
```

## API Usage

The gateway exposes an OpenAI-compatible API on port 9000 (configurable).

```bash
curl http://localhost:9000/v1/chat/completions \
  -H "x-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/nemotron-3-nano-4b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512
  }'
```

Streaming:

```bash
curl http://localhost:9000/v1/chat/completions \
  -H "x-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/nemotron-3-nano-4b",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512,
    "stream": true
  }'
```

Auth accepts either `x-api-key` header or `Authorization: Bearer <key>`. The `/health` endpoint requires no authentication.

## Cloudflare Tunnel (Public Exposure)

To expose the stack to the internet without opening router ports:

1. Provision a tunnel and DNS route (one-time, from a controlled machine):

```bash
cloudflared tunnel create llm-server
cloudflared tunnel route dns llm-server llm.jambu.ai
```

2. Place the credentials in the project:

```
cloudflared/
  ├── config.yml      # ingress rules
  └── tunnel.json     # credentials (secret — never commit)
```

3. The `cloudflared` service activates automatically when `cloudflared/tunnel.json` exists:

```bash
teoria-engine up     # detects tunnel.json → starts cloudflared profile
```

## Observability

The stack ships an OpenTelemetry Collector (`otel-collector` service) and the gateway is instrumented with OTLP traces.

Metrics worth monitoring:
- tokens/sec, TTFT, TPOT
- GPU utilization and memory
- Request latency and queue size

Configure the downstream backend in `otel/otel-collector-config.yml`.

## Testing

```bash
make test            # spin up mock vLLM stack, run integration + E2E tests, tear down
make test-smoke      # smoke tests against a real running stack (requires GPU + make up)
```

The test stack uses `docker-compose.test.yml` to override vLLM with a lightweight mock server — no GPU needed.

## systemd Service

Run as a system service that starts on boot:

```bash
sudo teoria-engine service      # install + enable + start
sudo teoria-engine unservice    # stop + disable + remove
```

## Project Structure

```
├── bin/
│   ├── teoria-engine        # main CLI
│   └── load-config          # YAML → shell env parser
├── config/
│   └── engine.yml           # model profiles and stack config
├── gateway/
│   ├── main.py              # FastAPI gateway (auth, streaming, telemetry)
│   ├── Dockerfile
│   └── requirements.txt
├── nginx/
│   └── nginx.conf           # reverse proxy with rate limiting
├── cloudflared/
│   ├── config.yml           # tunnel ingress rules
│   └── tunnel.json          # credentials (not committed)
├── otel/
│   └── otel-collector-config.yml
├── systemd/
│   └── teoria-engine.service
├── scripts/
│   └── install.sh           # one-line installer
├── tests/
│   ├── mock_vllm/           # lightweight mock for CI
│   ├── test_integration.py
│   ├── test_e2e.py
│   └── test_smoke.py
├── docker-compose.yml
├── docker-compose.test.yml
├── Makefile
├── .env.example
└── docs/
    ├── architecture.md
    └── validation.md
```

## License

Proprietary — Jambu.
