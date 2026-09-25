# Join HAL as a peer (FREE)

**Audience:** Another OpenAI-compatible client, MCP host, or someone adding an outbound peer.  
**Cost:** FREE examples only — patterns below do not require paid OpenAI/Anthropic keys.

HAL exposes an OpenAI-compatible gateway at [https://api.halsupreme.com](https://api.halsupreme.com). Access requires a Bearer token issued by maintainers. Never share real tokens in Discord, GitHub issues, or PRs—always use the placeholder <HAL_GATEWAY_TOKEN>.
Public peer page: https://halsupreme.com/peers.html

---

## 1. Point your client **at** HAL (inbound)

### OpenAI-compatible HTTP

| Setting | Value |
| --- | --- |
| Base URL | `https://api.halsupreme.com/v1` |
| Auth | `Authorization: Bearer <HAL_GATEWAY_TOKEN>` |
| Models | `hal/fast`, `hal/coder`, `hal/deep`, `hal/council` |

Example OpenCode / AI SDK style provider block (FREE — only needs a HAL peer/gateway token maintainers issue; no OpenAI/Anthropic paid key):

```json
{
  "provider": {
    "hal-supreme": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "HAL SUPREME",
      "options": {
        "baseURL": "https://api.halsupreme.com/v1",
        "apiKey": "<HAL_GATEWAY_TOKEN>"
      },
      "models": {
        "hal-fast": { "name": "hal/fast" },
        "hal-coder": { "name": "hal/coder" },
        "hal-deep": { "name": "hal/deep" },
        "hal-council": { "name": "hal/council" }
      }
    }
  }
}
```

curl smoke (replace the token placeholder):

```bash
curl -s https://api.halsupreme.com/health

curl -s https://api.halsupreme.com/v1/models \
  -H "Authorization: Bearer <HAL_GATEWAY_TOKEN>"

curl -s https://api.halsupreme.com/v1/peers \
  -H "Authorization: Bearer <HAL_GATEWAY_TOKEN>"

curl -s https://api.halsupreme.com/v1/chat/completions \
  -H "Authorization: Bearer <HAL_GATEWAY_TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"hal/fast\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}"
```

Without a Bearer token, `/v1/peers` and `/v1/models` return **401**.

### MCP (Cursor / Claude Desktop)

See [mcp-setup.md](mcp-setup.md). Local stdio MCP usually talks to a **local** gateway process; remote URL alone is often not enough for stdio MCP hosts.

---

## 2. Add an **outbound** peer (operator notes)

Maintainers configure outbound peers in a private peers config (not in this public repo). Public pattern for operators:

1. Add a peer entry with `base_url` pointing at the peer's OpenAI-compat root (usually ends in `/v1`).
2. Put the peer's secret in an **environment variable** named by `credential_env` — never paste secrets into config files or git.
3. Keep `"enabled": false` until a health probe succeeds.
4. Restart only the model gateway after changes. Do not expose tunnel credentials in docs or chat.

Example shape (still FREE path — friend's public Ollama/LiteLLM node; leave disabled until ready):

```json
{
  "version": "2026-09-23",
  "peers": {
    "friend-ollama": {
      "kind": "openai_compat",
      "name": "Friend Ollama (example)",
      "base_url": "https://peer.example.com/v1",
      "credential_env": "HAL_PEER_FRIEND_TOKEN",
      "auth_style": "bearer",
      "billing_class": "FREE",
      "privacy_class": "CLOUD_EXTERNAL",
      "allowed_models": ["llama3.2:3b", "qwen2.5:7b"],
      "capabilities": ["chat"],
      "rate_limit_rpm": 30,
      "enabled": false
    }
  }
}
```

`GET /v1/peers` returns HAL's self identity. **Enabled** peers are appended to the live list; disabled examples are omitted.

---

## 3. What peers can and cannot do

| Allowed | Not allowed |
| --- | --- |
| Auth'd `/v1/models`, `/v1/peers`, chat, documented tools via gateway/MCP | Maintainer disk access, internal control-plane mutate, minting tokens for others |

---

## 4. Related

- Public peer page: https://halsupreme.com/peers.html
- [MCP setup](mcp-setup.md)
- [Community hub](community-hub.md)
