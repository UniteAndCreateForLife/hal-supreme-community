# MCP setup for HAL SUPREME

Use this when connecting Cursor, Claude Desktop, or another MCP host to HAL.

## Important

- **Bearer tokens are issued by maintainers.** Never paste real tokens into Discord, Issues, Discussions, PRs, or committed files.
- MCP over **stdio** usually needs a **local** gateway process. Pointing `HAL_GATEWAY_URL` at the public API alone may not be enough for stdio MCP hosts.
- Public API base: `https://api.halsupreme.com`
- Typical local gateway (when you run one): `http://127.0.0.1:8766`

## Cursor `mcp.json` example

Placeholders only — adjust command availability on your machine. Do **not** hard-code personal absolute paths.

```json
{
  "mcpServers": {
    "hal-supreme": {
      "command": "python",
      "args": ["-m", "hal_mcp.gateway_server"],
      "env": {
        "HAL_GATEWAY_URL": "https://api.halsupreme.com"
      }
    }
  }
}
```

### Prefer local gateway for stdio

If the MCP server expects a local OpenAI-compatible gateway:

```json
{
  "mcpServers": {
    "hal-supreme": {
      "command": "python",
      "args": ["-m", "hal_mcp.gateway_server"],
      "env": {
        "HAL_GATEWAY_URL": "http://127.0.0.1:8766"
      }
    }
  }
}
```

Ensure `python -m hal_mcp.gateway_server` is available in the environment Cursor launches (venv activated or package on `PYTHONPATH` as you prefer). Use env vars for any auth the local gateway needs — never commit tokens.

## Auth reminder

Client and gateway auth use `Authorization: Bearer <HAL_GATEWAY_TOKEN>`. Without a valid token from maintainers, protected routes return **401**.

## Related

- [Peer join](peer-join.md)
- Product: https://halsupreme.com
- Peers page: https://halsupreme.com/peers.html
