# teoria-engine

Production-grade LLM inference stack. Runs on Linux with NVIDIA GPUs (via vLLM) or macOS Apple Silicon (via MLX). Orchestrates the LLM backend, a FastAPI gateway, NGINX reverse proxy, and optional Cloudflare tunnel — all managed through a single CLI.

Exposes an **OpenAI-compatible API** that any agent platform (Claude Code, Codex CLI, Cursor, Gemini CLI, OpenHands, LangChain, etc.) can use as a drop-in local LLM endpoint.

Default model: **nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16**.

### Available Model Profiles

| Profile | vLLM (Linux) | MLX (macOS) | Type |
|---|---|---|---|
| `nemotron` *(default)* | `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` | `mlx-community/Mistral-NeMo-Minitron-8B-Instruct-4bit` | Text / Tool calling |
| `qwen-0.5b` | `Qwen/Qwen2.5-0.5B-Instruct` | `mlx-community/Qwen2.5-0.5B-Instruct-4bit` | Text (lightweight) |
| `qwen3-vl-8b` | `unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit` | `mlx-community/Qwen3-VL-8B-Instruct-4bit` | Vision-Language |

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

`config/engine.yml` is the single source of truth for the entire stack. Secrets and hardware-specific values go in `.env`; everything else lives here.

#### Model profile fields

| Field | Description |
|---|---|
| `hf_name` | HuggingFace model ID used by vLLM (Linux + NVIDIA) |
| `mlx_name` | HuggingFace model ID used by MLX (macOS Apple Silicon) |
| `local_path` | Path to a local model directory for vLLM — relative to `local_models_dir` or absolute. Must be HuggingFace SafeTensors format. |
| `local_mlx_path` | Path to a local model for MLX — relative to `local_models_dir` or absolute. Supports both SafeTensors and GGUF. |
| `trust_remote_code` | Pass `--trust-remote-code` to vLLM |
| `max_model_len` | Maximum context length (tokens) |
| `gpu_memory_utilization` | Fraction of VRAM reserved for KV cache |
| `max_num_seqs` | Maximum concurrent sequences in flight |
| `max_num_batched_tokens` | Maximum tokens per batch |
| `prefix_caching` | Enable prefix caching (`--enable-prefix-caching`) |
| `chunked_prefill` | Enable chunked prefill (`--enable-chunked-prefill`) |
| `enforce_eager` | Disable CUDA graphs (`--enforce-eager`) — required for VL model stability |
| `async_scheduling` | Enable async scheduling (`--async-scheduling`) |
| `enable_auto_tool_choice` | Enable tool / function calling |
| `tool_call_parser` | Parser for tool calls: `llama3_json`, `mistral`, `hermes`, `internlm`, `granite-20b-fc` |
| `vllm_extra_args` | Raw string appended verbatim to the `vllm serve` command (for flags not covered above) |
| `gateway` | Per-model gateway overrides (see below) |

#### Per-model gateway overrides

Each profile can define a `gateway:` block that overrides the global `gateway:` defaults for that specific model. `bin/load-config` merges them at startup — the model wins, global is the fallback.

```yaml
models:
  your-model:
    hf_name: ...
    mlx_name: ...
    # ... vLLM settings ...
    gateway:
      max_input_tokens: 2048        # override global default
      max_output_tokens: 2048
      max_concurrent_requests: 2    # critical for memory-constrained models
      cache:
        enabled: false              # multimodal requests are unique; caching wastes memory
```

This means the `gateway:` top-level block is just the baseline — models that need tighter or looser limits declare it in their own profile, and the running stack enforces it automatically.

#### Local models directory (LM Studio / pre-downloaded)

Point the stack at models already on disk — no re-download needed. Compatible with LM Studio's model cache.

```yaml
# config/engine.yml

# Base directory where models are stored on the host.
# Auto-detected if left unset and the LM Studio default path exists.
local_models_dir: ~/.cache/lm-studio/models   # Linux default
# local_models_dir: ~/.lmstudio/models        # macOS default

models:
  qwen-0.5b:
    hf_name: Qwen/Qwen2.5-0.5B-Instruct
    mlx_name: mlx-community/Qwen2.5-0.5B-Instruct-4bit
    # vLLM: path relative to local_models_dir (SafeTensors format required, not GGUF)
    local_path: Qwen/Qwen2.5-0.5B-Instruct
    # MLX: supports both SafeTensors and GGUF
    local_mlx_path: lmstudio-community/Qwen2.5-0.5B-Instruct-GGUF/Qwen2.5-0.5B-Instruct-Q8_0.gguf
```

**How it works:**

| Backend | Mechanism |
|---|---|
| vLLM (Linux) | `local_models_dir` is bind-mounted read-only into the container at `/models/local`. vLLM receives `--model /models/local/<local_path>`. `HF_HUB_OFFLINE=1` prevents accidental downloads. |
| MLX (macOS) | `mlx_lm.server` receives the resolved absolute host path directly. No container involved. |

**Auto-detection:** If `local_models_dir` is not set, `bin/load-config` checks for the LM Studio default paths (`~/.cache/lm-studio/models` on Linux, `~/.lmstudio/models` on macOS) and uses them automatically when they exist.

**`.env.compose` (auto-generated):** Every `teoria-engine up`, `config`, or `preflight` call regenerates `.env.compose` with the resolved paths and flags. This file is passed to `docker compose` as a second `--env-file`, ensuring the compose runtime always has the correct `LOCAL_MODELS_DIR`, `VLLM_COMMAND`, and `HF_HUB_OFFLINE` values — even when `docker compose` is invoked directly without going through `bin/teoria-engine`. It is gitignored and should never be edited manually.

Verify what was detected:

```bash
teoria-engine preflight      # shows local_models_dir, file count, and per-model paths
teoria-engine config         # shows resolved model source (LOCAL vs HuggingFace)
```

> **vLLM format constraint:** vLLM requires HuggingFace SafeTensors format. GGUF files (common in LM Studio) are **not** supported by vLLM. Use `local_mlx_path` for GGUF models on macOS (MLX handles them natively). For Linux/vLLM, you need the SafeTensors version of the model.

#### Example: full profile reference

```yaml
active_model: nemotron

models:
  nemotron:
    hf_name: nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16
    mlx_name: mlx-community/Mistral-NeMo-Minitron-8B-Instruct-4bit
    trust_remote_code: true
    max_model_len: 131072
    gpu_memory_utilization: 0.95
    max_num_seqs: 256
    max_num_batched_tokens: 8192
    prefix_caching: true
    chunked_prefill: true
    enable_auto_tool_choice: true
    tool_call_parser: llama3_json

  qwen-0.5b:
    hf_name: Qwen/Qwen2.5-0.5B-Instruct
    mlx_name: mlx-community/Qwen2.5-0.5B-Instruct-4bit
    max_model_len: 4096
    gpu_memory_utilization: 0.50
    max_num_seqs: 64
    max_num_batched_tokens: 2048
    prefix_caching: true
    chunked_prefill: false
    enable_auto_tool_choice: false

  qwen3-vl-8b:
    hf_name: unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit
    mlx_name: mlx-community/Qwen3-VL-8B-Instruct-4bit
    trust_remote_code: true
    max_model_len: 4096
    gpu_memory_utilization: 0.82
    max_num_seqs: 2
    max_num_batched_tokens: 4096
    prefix_caching: false          # incompatible with --enforce-eager
    chunked_prefill: false
    enable_auto_tool_choice: false
    enforce_eager: true            # required for VL stability on 24 GB VRAM
    vllm_extra_args: "--disable-log-stats"
    gateway:
      max_input_tokens: 2048
      max_output_tokens: 2048
      max_concurrent_requests: 2   # hard limit — VL KV cache is unstable above 2
      cache:
        enabled: false

gateway:
  port: 9000
  max_input_tokens: 8000           # overridden per model when needed
  max_output_tokens: 2000
  max_concurrent_requests: 64
  cache:
    enabled: true
    max_entries: 2048
    ttl_seconds: 3600
```

Switch models without editing files:

```bash
teoria-engine config --model qwen3-vl-8b
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
  -H "Authorization: Bearer default" \
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

## Vision-Language Models (Qwen3-VL-8B)

The `qwen3-vl-8b` profile runs a vision-language model with hard operational constraints derived from 24 GB VRAM reality. Breaking any of these limits causes OOM or KV cache collapse.

### Operating envelope

| Constraint | Limit | Reason |
|---|---|---|
| Images per request | **1** | KV cache scales non-linearly with image patches |
| Image resolution | **512–768 px** (pre-resize mandatory) | Resolution is the main hidden VRAM driver |
| Context length | **≤ 4096 tokens** | Hard vLLM limit for this profile |
| Concurrent requests | **2** | Enforced by gateway `max_concurrent_requests` override |
| Max output tokens | **2048** | Enforced by gateway `max_output_tokens` override |

### Why `--enforce-eager`

vLLM uses CUDA graph capture by default to speed up inference. For vision-language models on 24 GB VRAM, CUDA graphs are unstable — they reserve additional memory at capture time that conflicts with the vision encoder's dynamic allocation. `enforce_eager: true` disables this, trading a small throughput regression for stability.

As a consequence, `prefix_caching` and `chunked_prefill` must also be disabled (they assume graph-mode execution internals).

### Recommended architecture for VL workloads

```
[MLX or vLLM — Vision stage]       [vLLM — Reasoning stage]
  receive image + prompt        →     receive structured caption / JSON
  extract: caption / JSON             run: analysis / generation
  max_tokens: 512–1024                max_tokens: 2048
```

Running two specialized stages instead of one large multimodal request reduces peak KV cache pressure, improves stability, and increases throughput.

### Sending images via the API

Images must be pre-resized to ≤ 768 px before sending. The model accepts standard OpenAI vision format:

```bash
curl https://llm.jambu.ai/v1/chat/completions \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
        {"type": "text", "text": "Describe this image in JSON."}
      ]
    }],
    "max_tokens": 512,
    "stream": true
  }'
```

> **Do not run VL like a standard LLM.** Monitor VRAM continuously (especially KV cache). Test with real inputs, not synthetic prompts.

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

## Agent Skill

teoria-engine ships as an [Agent Skill](https://agentskills.io) — a portable, installable capability that any compatible agent (Claude Code, OpenAI Codex CLI, Cursor, Gemini CLI, OpenHands, GitHub Copilot, and others) can discover and use to start, call, and stop a local LLM endpoint.

The skill lives at `teoria-engine/` in this repository.

### What the skill enables

Any agent that loads this skill can:

1. **Start** the engine on the user's machine (auto-detects vLLM vs MLX)
2. **Call** the OpenAI-compatible API for inference tasks
3. **Stop** the engine cleanly when done

### Quick integration — point any agent at the running gateway

```bash
export OPENAI_BASE_URL="http://localhost:9000/v1"
export OPENAI_API_KEY="$GATEWAY_API_KEY"
```

| Platform | Config |
|---|---|
| **Claude Code** | `OPENAI_BASE_URL=http://localhost:9000/v1 claude` |
| **Codex CLI** | `OPENAI_BASE_URL=http://localhost:9000/v1 codex ...` |
| **Cursor** | Settings → AI → OpenAI Base URL → `http://localhost:9000/v1` |
| **Gemini CLI** | `OPENAI_BASE_URL=http://localhost:9000/v1 gemini ...` |
| **OpenHands** | LLM config → Provider: OpenAI → Base URL: `http://localhost:9000/v1` |
| **Aider** | `aider --openai-api-base http://localhost:9000/v1 --openai-api-key $KEY` |
| **LangChain** | `ChatOpenAI(base_url="http://localhost:9000/v1", api_key=key)` |

Full per-platform instructions: [`teoria-engine/references/PLATFORMS.md`](teoria-engine/references/PLATFORMS.md)

### Skill structure

```
teoria-engine/
├── SKILL.md                        # skill definition (agentskills.io spec)
├── scripts/
│   ├── start.sh                    # idempotent start with health wait
│   ├── stop.sh                     # graceful stop
│   └── status.sh                   # health + endpoints + containers
├── references/
│   ├── REFERENCE.md                # full API + config reference
│   └── PLATFORMS.md                # per-platform agent integration
└── assets/
    ├── openai_client.py            # Python client example (sync, streaming, tools, VL)
    └── env.example                 # env template
```

## Project Structure

```
├── bin/
│   ├── teoria-engine        # main CLI (manages vLLM or MLX based on platform)
│   ├── load-config          # YAML → shell env parser + local path resolver
│   └── setup-tunnel         # Cloudflare tunnel one-time provisioning
├── config/
│   └── engine.yml           # single source of truth: model profiles + gateway + local paths
├── gateway/
│   ├── main.py              # FastAPI gateway (auth, caching, streaming, telemetry)
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
├── teoria-engine/           # Agent Skill (agentskills.io) — installable by any compatible agent
│   ├── SKILL.md
│   ├── scripts/             # start.sh / stop.sh / status.sh
│   ├── references/          # REFERENCE.md / PLATFORMS.md
│   └── assets/              # openai_client.py / env.example
├── tests/
│   ├── mock_vllm/           # lightweight mock for CI
│   ├── test_integration.py
│   ├── test_e2e.py
│   └── test_smoke.py
├── docker-compose.yml
├── docker-compose.test.yml
├── Makefile
├── .env.example
├── .env.compose             # auto-generated by teoria-engine (gitignored)
└── docs/
    ├── architecture.md
    ├── tunnel-deploy.md
    └── validation.md
```

## License

MIT — Jambu.ai
