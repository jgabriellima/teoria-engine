# LangChain and OpenAI-compatible clients — inference service checklist

This document lists what **LangChain** (`langchain-openai` / `ChatOpenAI`) and the **OpenAI Python SDK** expect from an HTTP inference surface. If your gateway or raw model server satisfies these points, it will work with LangChain and with most tools that target “OpenAI-compatible chat completions.”

For a runnable example against this project’s gateway, see `notebooks/teoria_api_langchain.ipynb`.

---

## 1. Scope: what actually talks to your service

| Client | Typical base URL | HTTP path | Notes |
|--------|------------------|-----------|--------|
| LangChain `ChatOpenAI` | `https://host/v1` | `POST /chat/completions` | Full URL = `https://host/v1/chat/completions` |
| OpenAI SDK `base_url=https://host/v1` | same | same | Same as above |
| Custom `/api/v1/chat` (this repo) | `https://host` | `POST /api/v1/chat` | **Not** used by `ChatOpenAI`; different JSON body (`input`, etc.). |

**Action:** To be “LangChain-compatible,” expose **`POST /v1/chat/completions`** (or proxy it transparently). A separate simplified API is optional and does not replace the OpenAI path for standard clients.

---

## 2. Authentication

Clients commonly send:

- `Authorization: Bearer <api_key>`, and/or  
- `x-api-key: <api_key>`

**Action:**

- Accept at least one of these (and document which you support).
- On failure, return **401** with a predictable JSON body if possible (many clients only check status code).

---

## 3. Non-streaming: `POST /v1/chat/completions`


### 3.1 Request body (minimum expectations)

Clients send JSON. You should accept:

| Field | Role |
|-------|------|
| `messages` | List of `{ "role": "system" \| "user" \| "assistant", "content": string \| ... }` |
| `model` | String; some clients always send it even if the server ignores it |
| `max_tokens` or `max_completion_tokens` | Either name appears in the wild (OpenAI moved toward `max_completion_tokens`) |
| `temperature`, `top_p`, `stop`, `frequency_penalty`, `presence_penalty` | Often forwarded if you support them |
| `stream` | `false` or omitted for non-streaming |

**Action:**

- Parse `messages` and forward them to the engine without dropping roles the engine supports.
- If `model` is optional on your side, still accept a non-empty string from the client and map it to the loaded model when needed (empty string can confuse some backends).
- Treat `max_completion_tokens` like `max_tokens` if you validate limits (this repo’s gateway checks both for the output cap).

### 3.2 Response body (200)

For **chat completions**, clients expect a JSON object shaped like OpenAI’s **chat** completion, including at least:

- `choices`: non-empty array  
- `choices[0].message`: `{ "role": "assistant", "content": "<text>" }`  
- `choices[0].finish_reason` (often `"stop"` or `null`)  
- Top-level `id`, `object`, `created`, `model` are commonly present; some parsers are strict.

**Action:** Return **valid JSON** (not NDJSON) with `choices[0].message.content` as the primary assistant text. Mismatches here break LangChain’s parser immediately.

### 3.3 Errors (4xx / 5xx)

**Implemented:** All gateway error responses use the nested OpenAI envelope:

```json
{ "error": { "message": "...", "type": "...", "code": "..." } }
```

| Scenario | `type` | `code` | HTTP status |
|----------|--------|--------|-------------|
| Missing / wrong key | `authentication_error` | `invalid_api_key` | 401 |
| `max_tokens` over limit | `invalid_request_error` | `null` | 400 |

This lets `openai.AuthenticationError` and `openai.BadRequestError` parse correctly without a fallback path. Avoid returning HTML error pages on API routes.

---

## 4. Streaming: `stream: true`

LangChain and the OpenAI SDK expect **Server-Sent Events (SSE)**:

- `Content-Type: text/event-stream`
- Lines starting with `data: ` followed by a JSON object **or** the literal `data: [DONE]`
- One event per chunk is typical; the last line is often `data: [DONE]\n\n`

Each JSON chunk should follow OpenAI’s **`chat.completion.chunk`** shape, with deltas under:

- `choices[0].delta.content` (incremental text; may be partial)
- Optional `choices[0].delta.role` on the first chunk

**Action:**

- Do not buffer the entire completion before flushing (reverse proxies must disable buffering for SSE — e.g. `X-Accel-Buffering: no` behind NGINX).
- Preserve byte-for-byte compatibility with your upstream (if you proxy, forward the stream without reformatting unless you know the format).

---

## 5. `GET /v1/models`

Some clients and health checks call **`/v1/models`** when `/health` is unavailable. LangChain's `ChatOpenAI` calls it implicitly when `list_models()` is invoked; the OpenAI SDK exposes it as `client.models.list()`.

**Implemented:** The gateway proxies `GET /v1/models` to the backend and returns the standard OpenAI list shape:

```json
{ "object": "list", "data": [{ "id": "model-id", "object": "model", "owned_by": "..." }] }
```

The route is auth-protected (same key as completions).

---

## 6. Transport and proxies

| Issue | Symptom | Mitigation |
|-------|---------|------------|
| SSE buffering | Stream arrives in one blob or times out | Disable proxy buffering; long `read_timeout` |
| HTTP/2 quirks | Rare client issues | Usually HTTP/1.1 for SSE is fine |
| Trailing gzip / wrong `Content-Type` | Parser errors | `text/event-stream` for streams, `application/json` for non-stream |

---

## 7. Simplified API vs OpenAI path (this project)

The gateway’s **`POST /api/v1/chat`** uses `input` / `system_prompt` and then translates to OpenAI format internally. That is convenient for curl and internal apps but **does not replace** `/v1/chat/completions` for LangChain.

**Action:** If your goal is “any OpenAI-style client,” keep **`/v1/chat/completions`** as the canonical contract. Use `/api/v1/chat` only as an extra layer, not as the sole API.

---

## 8. Internal consistency: health and tests

The gateway’s **`GET /health`** returns `{ "status", "backend": bool, "backend_url" }`. Tests previously asserted a legacy `vllm` key — those assertions have been updated to use `backend`.
---

## 9. Quick verification

Non-stream:

```bash
curl -sS "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"dummy","messages":[{"role":"user","content":"ping"}],"max_tokens":16}'
```

Stream:

```bash
curl -N "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"dummy","messages":[{"role":"user","content":"ping"}],"max_tokens":16,"stream":true}'
```

LangChain (Python) minimal pattern:

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

llm = ChatOpenAI(
    base_url=f"{BASE}/v1",
    api_key=API_KEY,
    model="dummy",  # server may override
)
llm.invoke([HumanMessage(content="ping")])
```

---

## 10. Summary checklist

- [x] **`POST /v1/chat/completions`** implemented or proxied without breaking JSON/SSE.
- [x] **`messages`** + optional **`model`** accepted; **`max_tokens`** / **`max_completion_tokens`** handled.
- [x] Non-stream response: **`choices[0].message.content`** present.
- [x] Stream: **SSE** with **`data: …`** lines and **`[DONE]`**.
- [x] **Auth**: `Bearer` and/or **`x-api-key`**.
- [x] **JSON errors** on failure — OpenAI-shaped `{ "error": { "message", "type", "code" } }`; no HTML on API routes.
- [x] Proxy: **no buffering** on SSE; adequate timeouts.
- [x] **`GET /v1/models`** proxied; auth-protected; returns standard list shape.
- [x] Health/monitoring JSON **matches** tests and dashboards (`backend` key).

---

## Related files in this repository

| File | Relevance |
|------|-----------|
| `gateway/main.py` | Auth, `/v1/chat/completions`, `/api/v1/chat`, streaming proxy |
| `nginx/nginx.conf` | `proxy_buffering off`, timeouts |
| `tests/test_integration.py` | Expected auth, streaming, `/api/v1/chat` response shape |
| `tests/mock_vllm/main.py` | Minimal OpenAI-compatible mock for local tests |
| `notebooks/teoria_api_langchain.ipynb` | LangChain + simplified API examples |
