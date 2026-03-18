# Validation Guide

## Test Layers

| Layer | Command | Requires GPU | What it validates |
|-------|---------|-------------|-------------------|
| Mock integration | `make test` | No | NGINX, gateway auth, streaming, rate limiting, concurrency |
| Smoke (real model) | `make test-smoke` | **Yes** | Real inference, model loading, vLLM batching, GPU health |

## Running Mock Tests (any machine)

```bash
make test
```

Spins up a mock vLLM + real gateway + real NGINX, runs 19 tests, tears down.

## Running Smoke Tests on GPU VM (Vast.ai or similar)

### 1. Create Instance

- Go to [vast.ai](https://vast.ai) (or RunPod, Lambda, etc.)
- Deploy a GPU instance:
  - **GPU**: RTX 4090 (24GB) or A100 (40/80GB)
  - **Image**: Docker + NVIDIA runtime pre-installed
  - **Disk**: 100GB+ (model weights download)
- Connect via SSH

### 2. Install

```bash
git clone https://github.com/jgabriellima/teoria-engine.git /opt/teoria-engine
cd /opt/teoria-engine
cp .env.example .env
```

### 3. Configure

```bash
nano .env
```

Set at minimum:

```
GATEWAY_API_KEY=<your-secure-key>
HUGGINGFACE_TOKEN=hf_...
```

Model configuration lives in `config/engine.yml`. The active model (`nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16`) is resolved by `bin/load-config` — no need to set `VLLM_MODEL` manually.

### 4. Preflight

```bash
teoria-engine preflight
```

Expected output:

```
[OK]   docker
[OK]   docker compose
[OK]   nvidia-smi detected
       NVIDIA RTX 4090, 24564 MiB
[OK]   nvidia container runtime
[OK]   .env present
=== preflight passed ===
```

### 5. Start

```bash
make up
```

First run downloads the model. Monitor with:

```bash
make logs
```

Wait until vLLM healthcheck passes (gateway and nginx start automatically after).

### 6. Validate

```bash
make health
make test-smoke

# Or test via public URL (if tunnel is configured):
curl -s https://llm.jambu.ai/health
curl -s -X POST https://llm.jambu.ai/api/v1/chat \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Hello","max_tokens":50,"stream":false}'
```

Expected: 8 tests pass covering real inference, streaming, multi-turn, concurrency.

### 7. Tear Down

```bash
make down
```

Then destroy the VM instance.

## Cost Estimate

| Phase | Duration | Cost (RTX 4090) |
|-------|----------|-----------------|
| Model download | ~10 min | ~$0.15 |
| Stack startup | ~2 min | ~$0.03 |
| Test execution | ~5 min | ~$0.08 |
| **Total** | **~17 min** | **~$0.26** |

RTX 4090 on Vast.ai: ~$0.30–0.50/hr. Full validation under $1.
