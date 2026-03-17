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

## Running Smoke Tests on RunPod

### 1. Create Instance

- Go to [runpod.io](https://runpod.io)
- Deploy a GPU Pod:
  - **GPU**: RTX 4090 (24GB) or A100 (40/80GB)
  - **Template**: RunPod Pytorch (has Docker + NVIDIA runtime pre-installed)
  - **Disk**: 100GB+ (model weights ~60GB)
- Connect via SSH

### 2. Install

```bash
curl -sSL https://raw.githubusercontent.com/jambu/teoria-llm-engine/main/scripts/install.sh | bash
cd /opt/teoria-engine
```

Or manually:

```bash
git clone https://github.com/jambu/teoria-llm-engine.git /opt/teoria-engine
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
VLLM_MODEL=nvidia/nemotron-3-nano-4b
```

If the model is gated (needs HuggingFace token), add to `.env`:

```
HUGGINGFACE_TOKEN=hf_...
```

And add to `docker-compose.yml` under the vllm service environment:

```yaml
- HUGGING_FACE_HUB_TOKEN=${HUGGINGFACE_TOKEN}
```

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

First run downloads the model (~60GB). Monitor with:

```bash
make logs
```

Wait until you see vLLM log:

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 6. Validate

```bash
make health
make test-smoke
```

Expected: 8 tests pass covering real inference, streaming, multi-turn, concurrency.

### 7. Tear Down

```bash
make down
```

Then destroy the RunPod instance.

## Cost Estimate

| Phase | Duration | Cost (RTX 4090) |
|-------|----------|-----------------|
| Model download | ~10 min | ~$0.15 |
| Stack startup | ~5 min | ~$0.08 |
| Test execution | ~5 min | ~$0.08 |
| **Total** | **~20 min** | **~$0.30** |

RTX 4090 on RunPod: ~$0.44/hr. Full validation under $1.
