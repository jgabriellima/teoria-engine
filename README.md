# teoria-engine

Production-grade LLM inference stack. Runs on Linux with NVIDIA GPUs (via vLLM) or macOS Apple Silicon (via MLX). Orchestrates the LLM backend, a FastAPI gateway, NGINX reverse proxy, and optional Cloudflare tunnel — all managed through a single CLI.

Default model: **nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16** (~31.6B params, ~3.6B active per token via MoE).

## Architecture

```
                  Linux + NVIDIA GPU                macOS Apple Silicon
                  ─────────────────                 ───────────────────

                  Internet                          localhost
                     │                                 │
                  Cloudflare Tunnel (opt)            NGINX (Docker)
                     │                                 │
                  NGINX (Docker)                    Gateway (Docker)
                     │                                 │
                  Gateway (Docker)                  MLX server (native)
                     │                                 │
                  vLLM (Docker, CUDA)               Metal GPU
                     │
                  GPU
```

Docker services: `gateway`, `nginx`, `openobserve`, `otel-collector`, `cloudflared` (opt-in profile), `vllm` (gpu profile, Linux only).

On macOS, the MLX server runs natively (Docker can't access Metal GPUs). The gateway inside Docker connects to it via `host.docker.internal`.

## Requirements

### Linux (production)

| Component | Minimum |
|---|---|
| GPU | RTX 4090 / RTX 6000 / A100 (24 GB+ VRAM) |
| RAM | 64 GB |
| Disk | NVMe SSD |
| OS | Ubuntu 22.04+ |
| CUDA | 12.4+ |
| Docker | Docker Engine + Compose plugin |
| Runtime | NVIDIA Container Toolkit |

### macOS (development)

| Component | Minimum |
|---|---|
| Chip | Apple Silicon (M1 / M2 / M3 / M4) |
| RAM | 16 GB (32 GB+ recommended) |
| OS | macOS 13+ |
| Docker | Docker Desktop |
| Python | 3.10+ with `mlx-lm` |

## Quick Start

**One-line install:**

```bash
curl -sSL https://raw.githubusercontent.com/jgabriellima/teoria-engine/main/scripts/install.sh | bash
```

Or with options:

```bash
curl -sSL https://raw.githubusercontent.com/jgabriellima/teoria-engine/main/scripts/install.sh | bash -s -- --install-dir /opt/teoria-engine --service
```

The installer auto-detects the platform, installs dependencies (`uv`, `mlx-lm` on Mac, NVIDIA Container Toolkit on Linux), and configures everything.

**Manual setup:**

```bash
git clone https://github.com/jgabriellima/teoria-engine.git /opt/teoria-engine
cd /opt/teoria-engine

cp .env.example .env          # set GATEWAY_API_KEY and HUGGINGFACE_TOKEN
teoria-engine preflight        # verify platform, GPU, docker
teoria-engine up               # start everything
teoria-engine health           # confirm it's running
```

**Uninstall:**

```bash
teoria-engine uninstall       # stops containers, removes volumes, files, and symlink
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

Each profile defines models for both platforms:

```yaml
active_model: nemotron

models:
  nemotron:
    hf_name: nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16           # vLLM (Linux)
    mlx_name: mlx-community/Mistral-NeMo-Minitron-8B-Instruct-4bit  # MLX (Mac)
    trust_remote_code: true
    max_model_len: 131072
    gpu_memory_utilization: 0.95
    max_num_seqs: 256
    max_num_batched_tokens: 8192
    prefix_caching: true
    chunked_prefill: true

  qwen-0.5b:
    hf_name: Qwen/Qwen2.5-0.5B-Instruct
    mlx_name: mlx-community/Qwen2.5-0.5B-Instruct-4bit
    max_model_len: 4096
    ...

mlx:
  port: 8000
  host: "0.0.0.0"
```

Switch models without editing files:

```bash
teoria-engine config --model qwen-0.5b
```

## CLI Reference

```
teoria-engine <command>

up                    Start all services (auto-detects backend)
down                  Stop all services
restart               Restart all services
logs [N]              Follow logs (last N lines, default 200)
status                Show container + backend status
health                Check gateway + LLM backend health
config [--model X]    Show resolved configuration
preflight             Check system prerequisites
help                  Show help
```

Linux-only:

```
service               Install as systemd service (requires root)
unservice             Remove systemd service (requires root)
```

All commands are also available via `make`:

```
make up            make down          make restart
make logs          make status        make health
make preflight     make service       make build
```

### What `teoria-engine up` does

| Platform | Behavior |
|---|---|
| Linux + NVIDIA | Activates `gpu` profile, starts vLLM container + gateway + nginx + observability |
| macOS Apple Silicon | Starts MLX server natively, then gateway + nginx + observability in Docker (gateway connects via `host.docker.internal`) |

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

The test stack uses `docker-compose.test.yml` to override vLLM with a lightweight mock server — no GPU needed. Tests run on any platform.

## systemd Service (Linux only)

Run as a system service that starts on boot:

```bash
sudo teoria-engine service      # install + enable + start
sudo teoria-engine unservice    # stop + disable + remove
```

## Project Structure

```
├── bin/
│   ├── teoria-engine        # main CLI (manages vLLM or MLX based on platform)
│   ├── load-config          # YAML → shell env parser
│   └── setup-tunnel         # Cloudflare tunnel one-time provisioning
├── config/
│   └── engine.yml           # model profiles (hf_name + mlx_name) and stack config
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
│   └── install.sh           # one-line installer (Linux + macOS)
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
