# teoria-engine — Platform Integration Guide

Assumes teoria-engine is running locally (`http://localhost:9000`).
For remote access via Cloudflare tunnel, replace with your `https://<hostname>`.

**Common variables** (set once in your shell profile):

```bash
export OPENAI_BASE_URL="http://localhost:9000/v1"
export OPENAI_API_KEY="<your-GATEWAY_API_KEY>"
```

---

## Claude Code

Claude Code can use an external OpenAI-compatible provider as its LLM backend.

```bash
# Set environment before launching Claude Code
export OPENAI_BASE_URL="http://localhost:9000/v1"
export OPENAI_API_KEY="$GATEWAY_API_KEY"

# Or pass inline
OPENAI_BASE_URL="http://localhost:9000/v1" \
OPENAI_API_KEY="$GATEWAY_API_KEY" \
claude --model auto

# Check available models first
claude models --list
```

For persistent config, add to `~/.claude/settings.json`:

```json
{
  "openaiBaseUrl": "http://localhost:9000/v1",
  "openaiApiKey": "<GATEWAY_API_KEY>"
}
```

> Note: Claude Code routes some requests to Anthropic by design. Use teoria-engine
> for tool/sub-agent calls by setting it as the default non-Anthropic provider.

---

## OpenAI Codex CLI

Codex CLI fully respects `OPENAI_BASE_URL` — it will hit teoria-engine instead of OpenAI.

```bash
export OPENAI_BASE_URL="http://localhost:9000/v1"
export OPENAI_API_KEY="$GATEWAY_API_KEY"

codex "Refactor this function to use async/await"
```

Or inline:

```bash
OPENAI_BASE_URL="http://localhost:9000/v1" \
OPENAI_API_KEY="$GATEWAY_API_KEY" \
codex --model auto "Explain this codebase"
```

Reddit community tip: vLLM returns OpenAI-compatible responses. If a model name is
required, use `"auto"` or match the exact model ID from `GET /v1/models`.

---

## Cursor

Cursor supports custom OpenAI-compatible endpoints for its AI features.

**Via Settings UI:**

1. Open **Cursor Settings** → **AI** → **OpenAI**
2. Set **Base URL**: `http://localhost:9000/v1`
3. Set **API Key**: `<GATEWAY_API_KEY>`
4. Set **Model**: `auto` (or the model ID from `/v1/models`)
5. Save and restart Cursor

**Via `.cursor/settings.json`** (project-level):

```json
{
  "ai": {
    "openai": {
      "baseUrl": "http://localhost:9000/v1",
      "apiKey": "<GATEWAY_API_KEY>",
      "model": "auto"
    }
  }
}
```

**Via environment** (useful for workspace configs):

```bash
# .env at project root (loaded by Cursor)
OPENAI_BASE_URL=http://localhost:9000/v1
OPENAI_API_KEY=<GATEWAY_API_KEY>
```

---

## Gemini CLI

Gemini CLI supports OpenAI-compatible endpoints via environment variables.

```bash
export OPENAI_BASE_URL="http://localhost:9000/v1"
export OPENAI_API_KEY="$GATEWAY_API_KEY"
export GEMINI_MODEL="auto"   # or exact model ID

gemini "Write a Dockerfile for a FastAPI app"
```

For persistent config in `~/.gemini/settings.json`:

```json
{
  "llmProvider": "openai-compatible",
  "openaiBaseUrl": "http://localhost:9000/v1",
  "openaiApiKey": "<GATEWAY_API_KEY>",
  "model": "auto"
}
```

---

## OpenHands (formerly OpenDevin)

OpenHands ships a web UI with LLM provider configuration.

**Via web UI:**

1. Start OpenHands: `docker run -p 3000:3000 ghcr.io/all-hands-ai/openhands:latest`
2. Open `http://localhost:3000`
3. Go to **Settings** → **LLM**
4. Set **Provider**: `OpenAI`
5. Set **Base URL**: `http://host.docker.internal:9000/v1`  
   *(use `host.docker.internal` from inside Docker, or `http://localhost:9000/v1` if running natively)*
6. Set **API Key**: `<GATEWAY_API_KEY>`
7. Set **Model**: `auto`

**Via environment variables:**

```bash
docker run -p 3000:3000 \
  -e LLM_BASE_URL="http://host.docker.internal:9000/v1" \
  -e LLM_API_KEY="$GATEWAY_API_KEY" \
  -e LLM_MODEL="auto" \
  ghcr.io/all-hands-ai/openhands:latest
```

**Via `config.toml`:**

```toml
[llm]
base_url = "http://localhost:9000/v1"
api_key = "<GATEWAY_API_KEY>"
model = "openai/auto"
```

---

## Aider

Aider is a terminal-based coding assistant that works with any OpenAI-compatible backend.

```bash
# One-off
aider \
  --openai-api-base "http://localhost:9000/v1" \
  --openai-api-key "$GATEWAY_API_KEY" \
  --model "openai/auto"

# Persistent (add to ~/.aider.conf.yml)
openai-api-base: http://localhost:9000/v1
openai-api-key: <GATEWAY_API_KEY>
model: openai/auto
```

Streaming is fully supported and recommended for large outputs.

---

## LangChain (Python)

```python
from langchain_openai import ChatOpenAI
import os

llm = ChatOpenAI(
    base_url="http://localhost:9000/v1",
    api_key=os.getenv("GATEWAY_API_KEY", "default"),
    model="auto",
    temperature=0.7,
    streaming=True,
)

response = llm.invoke("Summarize the CAP theorem in 3 bullet points.")
print(response.content)
```

With tool calling (requires `nemotron` profile with `enable_auto_tool_choice: true`):

```python
from langchain_core.tools import tool

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

llm_with_tools = llm.bind_tools([search_web])
result = llm_with_tools.invoke("What is vLLM?")
```

---

## LlamaIndex (Python)

```python
from llama_index.llms.openai import OpenAI
import os

llm = OpenAI(
    api_base="http://localhost:9000/v1",
    api_key=os.getenv("GATEWAY_API_KEY", "default"),
    model="auto",
)

from llama_index.core import Settings
Settings.llm = llm

response = llm.complete("Explain retrieval-augmented generation.")
print(response.text)
```

---

## AutoGen / AG2

```python
import autogen

config_list = [{
    "model": "auto",
    "base_url": "http://localhost:9000/v1",
    "api_key": os.getenv("GATEWAY_API_KEY"),
    "api_type": "openai",
}]

assistant = autogen.AssistantAgent(
    name="assistant",
    llm_config={"config_list": config_list, "cache_seed": None},
)

user = autogen.UserProxyAgent(name="user", human_input_mode="NEVER")
user.initiate_chat(assistant, message="Write a Python web scraper.")
```

---

## CrewAI

```python
from crewai import Agent, Task, Crew, LLM

llm = LLM(
    model="openai/auto",
    base_url="http://localhost:9000/v1",
    api_key=os.getenv("GATEWAY_API_KEY"),
)

researcher = Agent(
    role="Researcher",
    goal="Research AI inference optimization",
    backstory="Expert in LLM systems.",
    llm=llm,
    verbose=True,
)
```

---

## Raw Python (openai SDK)

```python
from openai import OpenAI
import os

client = OpenAI(
    base_url="http://localhost:9000/v1",
    api_key=os.getenv("GATEWAY_API_KEY", "default"),
)

# Synchronous
resp = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=512,
)
print(resp.choices[0].message.content)

# Streaming
with client.chat.completions.stream(
    model="auto",
    messages=[{"role": "user", "content": "Count to 10"}],
    max_tokens=128,
) as stream:
    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
```

---

## curl / HTTP

```bash
BASE="http://localhost:9000"
KEY="$GATEWAY_API_KEY"

# Health (no auth)
curl -sf "${BASE}/health" | jq .

# List models
curl "${BASE}/v1/models" -H "x-api-key: ${KEY}" | jq '.data[].id'

# Chat completions
curl "${BASE}/v1/chat/completions" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 128}'

# Streaming
curl -N "${BASE}/v1/chat/completions" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Count to 5"}], "max_tokens": 64, "stream": true}'

# Simplified API
curl "${BASE}/api/v1/chat" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Content-Type: application/json" \
  -d '{"input": "Explain RLHF", "system_prompt": "Be concise.", "temperature": 0}'
```

---

## Remote access via Cloudflare tunnel

When `cloudflared/tunnel.json` is present and the tunnel profile is active, the stack
is exposed at the configured hostname (e.g. `https://llm.jambu.ai`).

Replace `http://localhost:9000` with `https://<your-hostname>` in all configs above.
Auth is the same — `GATEWAY_API_KEY` is enforced by the gateway layer before NGINX.

---

## Quick verification (any platform)

After configuring your client, verify the integration:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:9000/v1", api_key="<key>")
models = client.models.list()
print([m.id for m in models.data])
resp = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Say 'OK' if you can hear me."}],
    max_tokens=10,
)
print(resp.choices[0].message.content)
```

Expected output: model ID printed, then `OK` (or similar).
