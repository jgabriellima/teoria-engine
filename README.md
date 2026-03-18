# teoria-engine

Production-grade LLM inference stack for single GPU nodes. Orchestrates vLLM, a FastAPI gateway, NGINX reverse proxy, and optional Cloudflare tunnel — all managed through a single CLI.

Default model: **nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16** (~31.6B params, ~3.6B active per token via MoE).

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
curl -sSL https://raw.githubusercontent.com/jgabriellima/teoria-engine/main/scripts/install.sh | bash
```

Or with options:

```bash
curl -sSL https://raw.githubusercontent.com/jgabriellima/teoria-engine/main/scripts/install.sh | bash -s -- --install-dir /opt/teoria-engine --service
```

**Manual setup:**

```bash
git clone https://github.com/jgabriellima/teoria-engine.git /opt/teoria-engine
cd /opt/teoria-engine

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
    hf_name: nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16
    trust_remote_code: true
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

The gateway exposes an OpenAI-compatible API on port 9000 (configurable). With the Cloudflare tunnel active, the public URL is `https://llm.jambu.ai`.

```bash
# Via public URL (with tunnel)
curl https://llm.jambu.ai/v1/chat/completions \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512
  }'

# Via localhost (direct / SSH tunnel)
curl http://localhost:9000/v1/chat/completions \
  -H "x-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512
  }'
```

Streaming (OpenAI-compatible):

```bash
curl -N https://llm.jambu.ai/v1/chat/completions \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512,
    "stream": true
  }'
```

Streaming (simplified API):

```bash
curl -N https://llm.jambu.ai/api/v1/chat \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Count from 1 to 10, one per line",
    "max_tokens": 100,
    "stream": true
  }'
```

Auth accepts either `x-api-key` header or `Authorization: Bearer <key>`. The `/health` endpoint requires no authentication. The model field is optional — the gateway resolves it to the active model automatically.

### Simplified API (`/api/v1/chat`)

Task-oriented contract with `system_prompt` + `input`:

```bash
curl https://llm.jambu.ai/api/v1/chat \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Compute exactly: 93847 × 76429",
    "system_prompt": "Compute the exact result. Show reasoning and then provide the final integer.",
    "temperature": 0,
    "max_tokens": 512
  }'
```

| Field          | Type    | Required | Default | Description                    |
|----------------|---------|----------|---------|--------------------------------|
| `input`        | string  | yes      | —       | User prompt                    |
| `system_prompt`| string  | no       | —       | System instruction              |
| `model`        | string  | no       | —       | Model ID (uses server default) |
| `temperature`  | float   | no       | 0.7     | Sampling temperature (0–2)     |
| `max_tokens`   | int     | no       | 2048    | Max completion tokens          |
| `stream`       | boolean | no       | false   | Stream response                |

## Cloudflare Tunnel (Public Exposure)

To expose the stack to the internet without opening router ports:

1. **One-time provisioning** (run locally on a machine with `cloudflared` and browser for login):

```bash
bin/setup-tunnel
```

This installs `cloudflared/config.yml` from `config/engine.yml` (tunnel section) — the config is versioned with the project. Then it provisions the tunnel and copies credentials.

Or manually:

```bash
cloudflared tunnel login
cloudflared tunnel create llm-server
cloudflared tunnel route dns llm-server llm.jambu.ai
# Copy ~/.cloudflared/<tunnel-id>.json to cloudflared/tunnel.json
# Or: bin/setup-tunnel --credentials ~/.cloudflared/<tunnel-id>.json
```

2. **Deploy to VM**: copy `cloudflared/tunnel.json` securely (e.g. `scp`) to the VM at `/opt/teoria-engine/cloudflared/`. The tunnel starts automatically with `make up`.

3. The `cloudflared` service activates when `cloudflared/tunnel.json` exists:

```bash
teoria-engine up     # detects tunnel.json → starts cloudflared profile
```

4. **Test**:

```bash
curl -s https://llm.jambu.ai/health
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
│   ├── load-config          # YAML → shell env parser
│   └── setup-tunnel         # Cloudflare tunnel one-time provisioning
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
    ├── tunnel-deploy.md
    └── validation.md
```

## License

MIT — Jambu.ai

