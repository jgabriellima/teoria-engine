# Engineering Deployment Guide

## Production Serving of `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16`

---

# 1. Model Overview

Nemotron‑3 Nano is part of NVIDIA's Nemotron‑3 family designed for efficient agentic reasoning workloads.

Key characteristics:

* Hybrid **Mamba‑2 + Transformer** architecture
* **Mixture‑of‑Experts (MoE)** network
* ~31.6B total parameters
* ~3.6B active parameters per token
* Designed for **high‑throughput inference**

The architecture activates only a subset of experts per token, reducing compute while maintaining reasoning performance.

Implication:

* High throughput
* Lower latency
* Efficient GPU usage

---

# 2. Recommended Inference Engine

**vLLM is the recommended inference engine.**

Reasons:

* Continuous batching
* PagedAttention memory management
* KV‑cache efficiency
* Production grade OpenAI compatible API

Alternative engines (not recommended unless required):

* TensorRT‑LLM
* Triton Server

---

# 3. Infrastructure Architecture

```
Internet
   │
Load Balancer / Cloudflare
   │
NGINX Reverse Proxy
   │
API Gateway (FastAPI)
   │
vLLM Inference Server
   │
GPU Node
```

Design goals:

* Isolation of LLM runtime
* Restart safety
* Rate limiting
* Observability

---

# 4. Hardware Requirements

Minimum:

GPU:

* RTX 4090
* RTX 6000
* A100

VRAM:

Minimum 24GB

System RAM:

Minimum 64GB

Disk:

NVMe SSD

---

# 5. Environment Setup

OS:

Ubuntu 22.04

Dependencies:

```
CUDA 12.4+
Docker
Docker Compose
NVIDIA Container Toolkit
```

Install NVIDIA runtime:

```
sudo apt install nvidia-container-toolkit
sudo systemctl restart docker
```

---

# 6. Container Architecture

Docker Compose configuration

```
version: '3.9'

services:

  vllm:

    image: vllm/vllm-openai:latest

    runtime: nvidia

    environment:

      - NVIDIA_VISIBLE_DEVICES=0

    ports:

      - "8000:8000"

    command: >

      --model nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16
      --gpu-memory-utilization 0.95
      --max-model-len 131072
      --max-num-seqs 256
      --max-num-batched-tokens 8192
      --enable-prefix-caching
      --enable-chunked-prefill

    restart: always
```

---

# 7. Gateway Service

FastAPI wrapper

Responsibilities:

* authentication
* rate limit
* logging
* retries
* model routing

Example implementation

```python
from fastapi import FastAPI
import httpx

app = FastAPI()

LLM_URL = "http://vllm:8000/v1/chat/completions"

@app.post("/chat")
async def chat(payload: dict):

    async with httpx.AsyncClient(timeout=300) as client:

        r = await client.post(LLM_URL, json=payload)

    return r.json()
```

---

# 8. Reverse Proxy

NGINX configuration

```
server {

  listen 80;

  location / {

    proxy_pass http://gateway:9000;

    proxy_http_version 1.1;

    proxy_set_header Host $host;

    proxy_set_header X-Real-IP $remote_addr;

    proxy_read_timeout 300;

  }

}
```

---

# 9. Performance Configuration

Key parameters:

```
--gpu-memory-utilization 0.95
--max-num-seqs 256
--max-num-batched-tokens 8192
--enable-prefix-caching
--enable-chunked-prefill
```

Explanation

GPU utilization:

Maximize KV cache allocation.

Batch tokens:

Controls concurrent inference.

Prefix caching:

Improves performance when prompts share prefixes.

Chunked prefill:

Reduces latency for long contexts.

---

# 10. Observability

Recommended stack:

**OpenObserve** (replacing Prometheus + Loki)

Reasons:

* Unified logs, metrics, and traces
* Lower operational complexity
* High ingestion performance
* Compatible with OpenTelemetry

Architecture:

```
LLM Server
   │
OpenTelemetry Collector
   │
OpenObserve
```

Metrics to capture:

* tokens/sec
* time to first token (TTFT)
* time per output token (TPOT)
* GPU utilization
* GPU memory usage
* request latency
* request queue size

Example OpenTelemetry instrumentation in the gateway:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("llm_request"):
    response = await client.post(LLM_URL, json=payload)
```

Logs from vLLM container should be shipped using a lightweight collector (Vector or FluentBit).

---

# 11. Health Monitoring

Health Monitoring

Endpoint:

```
GET /health
```

Implementation should:

* send minimal inference request
* validate GPU execution

---

# 12. Auto‑Recovery

Systemd watchdog

```
Restart=always
RestartSec=5
```

Daily restart recommended

```
0 4 * * * docker restart vllm
```

Reason:

GPU memory fragmentation over long sessions.

---

# 13. Expected Performance

Typical metrics:

Throughput:

~150‑200 tokens/sec

TTFT:

~1 second

Concurrency:

50‑200 requests depending on context.

---

# 14. Security

Required protections

* API authentication
* rate limiting
* request size limits

Recommended:

Cloudflare or API Gateway.

---

# 15. Scaling Strategy

Current deployment constraint:

**Single GPU node**

Therefore scaling must focus on **maximizing GPU utilization rather than horizontal scaling**.

Optimization strategies:

1. Continuous batching (handled by vLLM)
2. Prefix caching enabled
3. Large batch token capacity
4. High GPU memory allocation for KV cache

Recommended parameters for single GPU:

```
--gpu-memory-utilization 0.95
--max-num-seqs 256
--max-num-batched-tokens 8192
--enable-prefix-caching
--enable-chunked-prefill
```

If the workload grows beyond the single GPU capacity, the architecture can evolve to:

```
GPU Node A
GPU Node B
GPU Node C

Load Balancer
```

Using:

* NGINX upstream
* Kubernetes
* Ray Serve

However the current design remains fully compatible with future multi-GPU scaling.

---

# 16. Production Checklist. Production Checklist

Before go‑live:

* GPU monitoring configured
* logs centralized
* health checks active
* restart policies configured
* rate limiting enabled

---

# 17. Public Internet Exposure

The GPU node must be exposed to the internet through a secure tunnel and reverse proxy architecture. Direct port forwarding is **not allowed** because it exposes the machine to attacks and removes DDoS protection.

Recommended architecture:

```
Internet
   │
Cloudflare Edge
   │
Cloudflare Tunnel (cloudflared)
   │
NGINX Reverse Proxy
   │
Gateway API (FastAPI)
   │
vLLM Server
   │
GPU
```

This architecture ensures:

* TLS termination
* DDoS protection
* no open router ports
* stable public endpoint

---

# 17.1 Cloudflare Tunnel Setup

Install cloudflared:

```
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

Authenticate with Cloudflare:

```
cloudflared tunnel login
```

Create the tunnel:

```
cloudflared tunnel create llm-server
```

Configuration file:

```
~/.cloudflared/config.yml
```

```
tunnel: llm-server
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:

  - hostname: llm.yourdomain.com
    service: http://localhost:80

  - service: http_status:404
```

Run the tunnel:

```
cloudflared tunnel run llm-server
```

The model endpoint will then be accessible through:

```
https://llm.yourdomain.com
```

---

# 17.2 Reverse Proxy Configuration

NGINX must be configured to support streaming responses from the LLM server.

Example configuration:

```
server {

  listen 80;

  location / {

    proxy_pass http://gateway:9000;

    proxy_http_version 1.1;

    proxy_set_header Connection '';

    proxy_set_header Host $host;

    proxy_set_header X-Real-IP $remote_addr;

    proxy_buffering off;

    proxy_read_timeout 3600;

  }

}
```

Important parameters:

* `proxy_buffering off` enables token streaming
* long read timeout prevents request termination during generation

---

# 17.3 Rate Limiting

The public endpoint must enforce rate limits to protect the GPU from overload.

NGINX configuration example:

```
limit_req_zone $binary_remote_addr zone=llm:10m rate=5r/s;

server {

  location / {

    limit_req zone=llm burst=20;

    proxy_pass http://gateway:9000;

  }

}
```

---

# 17.4 API Authentication

The gateway must require an API key for every request.

Example implementation:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

API_KEY = "CHANGE_ME"

app = FastAPI()

@app.middleware("http")
async def authenticate(request: Request, call_next):

    if request.headers.get("x-api-key") != API_KEY:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    return await call_next(request)
```

---

# 17.5 Resource Protection

The gateway must enforce limits to avoid GPU exhaustion.

Recommended safeguards:

* maximum prompt tokens
* maximum generation tokens
* concurrency limits

Example constraints:

```
max_input_tokens = 8000
max_output_tokens = 2000
max_concurrent_requests = 64
```

---

# 18. Non-Interactive Cloudflare Tunnel (Production Mode)

The tunnel must be provisioned once and then executed without any interactive login on runtime machines.

## 18.1 Provisioning (one-time, by platform owner)

Run on a controlled machine:

```
cloudflared tunnel create llm-server
cloudflared tunnel route dns llm-server llm.jambu.ai
```

This generates a credentials file:

```
~/.cloudflared/<tunnel-id>.json
```

This file is the **tunnel identity** and must be treated as a secret.

## 18.2 Artifacts to deliver to runtime environments

Provide the following files to the deployment bundle (do NOT require login):

```
/app/cloudflared/
  ├── config.yml
  └── tunnel.json   (renamed from <tunnel-id>.json)
```

## 18.3 config.yml (production-ready)

```
tunnel: llm-server
credentials-file: /etc/cloudflared/tunnel.json

ingress:
  - hostname: llm.jambu.ai
    service: http://nginx:80
  - service: http_status:404
```

## 18.4 Dockerized execution (recommended)

Add a dedicated service for the tunnel. No login is required at runtime.

```
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --config /etc/cloudflared/config.yml run
    volumes:
      - ./cloudflared:/etc/cloudflared
    restart: always
    depends_on:
      - nginx
```

## 18.5 Startup command (non-Docker alternative)

```
cloudflared --config /etc/cloudflared/config.yml tunnel run
```

## 18.6 Security requirements

* The `tunnel.json` file is a sensitive credential (equivalent to a root API key for the tunnel).
* NEVER commit it to public repositories.
* Store it using a secrets manager (Vault, SSM, Docker secrets) when possible.
* Restrict filesystem permissions (chmod 600).

## 18.7 Separation of concerns

Provisioning (done once):

* create tunnel
* create DNS route
* generate credentials

Runtime (every deploy):

* mount config + credentials
* start cloudflared container

No human interaction is allowed during runtime.
