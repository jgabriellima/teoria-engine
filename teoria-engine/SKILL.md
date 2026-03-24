---
name: teoria-engine
description: >
  Starts, uses, and stops a production-grade self-hosted LLM inference stack (teoria-engine).
  Provides an OpenAI-compatible API backed by vLLM (Linux + NVIDIA GPU) or MLX (macOS Apple Silicon)
  with a FastAPI gateway, NGINX, optional Cloudflare tunnel, and full observability.
  Activate when the user needs to run a local/private LLM, serve AI to other agents at maximum
  performance, switch model profiles (text, vision-language, lightweight), or shut the stack down
  cleanly. Also activate when any tool needs OPENAI_BASE_URL pointing to a local inference server.
license: MIT
compatibility: >
  Linux (Ubuntu 22.04+, NVIDIA GPU ≥24 GB VRAM, CUDA 12.4+, Docker + NVIDIA Container Toolkit)
  OR macOS Apple Silicon (M1–M4, ≥16 GB RAM, Docker Desktop, Python 3.10+ with mlx-lm).
  Requires Git, Bash, Docker Compose v2+.
metadata:
  author: jambu.ai
  version: "1.0"
  github: https://github.com/jgabriellima/teoria-engine
  api-compat: openai-v1
allowed-tools: Bash(*) Read Write
---

# teoria-engine

Production-grade self-hosted LLM stack. Two backends, one gateway, OpenAI-compatible API.

| Platform | Backend | GPU |
|---|---|---|
| Linux + NVIDIA | vLLM (Docker) | CUDA |
| macOS Apple Silicon | MLX (native) | Metal |

## When to use this skill

- User needs a local/private LLM endpoint
- Another tool requires `OPENAI_BASE_URL` or `OPENAI_API_KEY` pointing to a local server
- User wants to serve models to other agents (Claude Code, Codex, Cursor, Gemini CLI, OpenHands)
- User wants to start, stop, or switch model profiles
- User needs vision-language inference (`qwen3-vl-8b`)

---

## Step 1 — Check if already running

```bash
# Quick health check — no auth needed
curl -sf http://localhost:9000/health && echo "RUNNING" || echo "NOT RUNNING"
```

If already running, skip to [Step 4 — Call the API](#step-4--call-the-api).

Run the status script for full details:

```bash
bash teoria-engine/scripts/status.sh
```

---

## Step 2 — Install (first time only)

One-line installer (auto-detects Linux/macOS, installs all dependencies):

```bash
curl -sSL https://raw.githubusercontent.com/jgabriellima/teoria-engine/main/scripts/install.sh | bash
```

Or clone manually:

```bash
git clone https://github.com/jgabriellima/teoria-engine.git /opt/teoria-engine
cd /opt/teoria-engine
cp .env.example .env
# Edit .env: set GATEWAY_API_KEY and HUGGINGFACE_TOKEN
```

Verify system prerequisites before the first start:

```bash
teoria-engine preflight
```

---

## Step 3 — Start the engine

```bash
# Smart start (detects platform, selects backend automatically)
bash teoria-engine/scripts/start.sh

# Or directly via CLI
cd /opt/teoria-engine && teoria-engine up

# With a specific model profile
cd /opt/teoria-engine && teoria-engine config --model qwen-0.5b && teoria-engine up
```

**Available model profiles:**

| Profile | vLLM (Linux) | MLX (macOS) | Best for |
|---|---|---|---|
| `nemotron` *(default)* | nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16 | mlx-community/Mistral-NeMo-Minitron-8B-Instruct-4bit | Text + tool calling |
| `qwen-0.5b` | Qwen/Qwen2.5-0.5B-Instruct | mlx-community/Qwen2.5-0.5B-Instruct-4bit | Lightweight / fast |
| `qwen3-vl-8b` | unsloth/Qwen3-VL-8B-Instruct-unsloth-bnb-4bit | mlx-community/Qwen3-VL-8B-Instruct-4bit | Vision-language |

Wait for readiness (the model loads into VRAM — allow 60–120 s):

```bash
bash teoria-engine/scripts/status.sh --wait
```

---

## Step 4 — Call the API

**Base URL:** `http://localhost:9000`  
**Auth:** `x-api-key: <GATEWAY_API_KEY>` or `Authorization: Bearer <GATEWAY_API_KEY>`  
**Model field:** optional — gateway resolves to active model if omitted

### curl

```bash
curl http://localhost:9000/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 512}'
```

Streaming:

```bash
curl -N http://localhost:9000/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "List 5 planets"}, ], "max_tokens": 256, "stream": true}'
```

### Python (openai SDK — drop-in)

```python
from openai import OpenAI
import os

client = OpenAI(
    base_url="http://localhost:9000/v1",
    api_key=os.getenv("GATEWAY_API_KEY", "default"),
)

resp = client.chat.completions.create(
    model="auto",   # gateway selects active model
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=512,
)
print(resp.choices[0].message.content)
```

See `assets/openai_client.py` for a complete example including streaming and tool calling.

### Simplified task API (`/api/v1/chat`)

```bash
curl http://localhost:9000/api/v1/chat \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": "Summarize quantum entanglement in 3 sentences", "system_prompt": "Be concise.", "temperature": 0}'
```

### Vision-Language (qwen3-vl-8b only)

```bash
curl http://localhost:9000/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
        {"type": "text", "text": "Describe this image in JSON."}
      ]
    }],
    "max_tokens": 512
  }'
```

> VL constraint: 1 image per request, pre-resize to ≤768 px, max 2 concurrent requests.

---

## Step 5 — Connect an agent platform

Point any OpenAI-compatible client at the gateway. See [references/PLATFORMS.md](references/PLATFORMS.md) for full per-platform config.

**Quick reference:**

| Platform | Config |
|---|---|
| **Claude Code** | `ANTHROPIC_BASE_URL` or `--openai-base-url http://localhost:9000/v1` |
| **OpenAI Codex CLI** | `OPENAI_BASE_URL=http://localhost:9000/v1` |
| **Cursor** | Settings → OpenAI Base URL → `http://localhost:9000/v1` |
| **Gemini CLI** | `OPENAI_BASE_URL=http://localhost:9000/v1 OPENAI_API_KEY=$GATEWAY_API_KEY` |
| **OpenHands** | LLM config → Provider: OpenAI → Base URL: `http://localhost:9000/v1` |
| **LangChain** | `ChatOpenAI(base_url="http://localhost:9000/v1", api_key=key)` |
| **LlamaIndex** | `OpenAI(api_base="http://localhost:9000/v1", api_key=key)` |
| **Aider** | `aider --openai-api-base http://localhost:9000/v1 --openai-api-key $KEY` |

---

## Step 6 — Stop the engine

```bash
bash teoria-engine/scripts/stop.sh

# Or directly
cd /opt/teoria-engine && teoria-engine down
```

---

## Lifecycle commands

```bash
teoria-engine up           # start all services
teoria-engine down         # stop all services  
teoria-engine restart      # restart
teoria-engine health       # check gateway + backend health
teoria-engine status       # container status
teoria-engine logs [N]     # follow logs (last N lines)
teoria-engine config --model <profile>   # switch model profile
```

---

## Key operational limits

| Limit | Default | Override |
|---|---|---|
| Max input tokens | 8 000 | `gateway.max_input_tokens` in `config/engine.yml` |
| Max output tokens | 2 000 | `gateway.max_output_tokens` in `config/engine.yml` |
| Max concurrent requests | 64 | `gateway.max_concurrent_requests` in `config/engine.yml` |
| Rate limit | 5 req/s | `nginx.rate_limit` in `config/engine.yml` |
| Response cache TTL | 3 600 s | `gateway.cache.ttl_seconds` (temp=0 only) |

---

## Troubleshooting

**Gateway returns 503:**
```bash
# Check backend health
curl http://localhost:9000/health
# Tail logs
cd /opt/teoria-engine && teoria-engine logs 100
```

**Port 9000 already in use:**
```bash
lsof -i :9000
# Change GATEWAY_PORT in .env and rebuild
```

**VRAM OOM (Linux):**
- Reduce `gpu_memory_utilization` in `config/engine.yml` for the active profile
- Switch to `qwen-0.5b` profile for lower VRAM footprint

**MLX server not starting (macOS):**
```bash
pip install mlx-lm && which mlx_lm.server
```

For complete API reference and all config fields, see [references/REFERENCE.md](references/REFERENCE.md).  
For platform-specific integration guides, see [references/PLATFORMS.md](references/PLATFORMS.md).
