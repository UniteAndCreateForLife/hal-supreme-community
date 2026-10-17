# External Agent Connectors

HAL SUPREME exposes a public MCP endpoint for approved remote agents:

`https://mcp.halsupreme.com/mcp`

This directory contains public-safe connector templates. **No credential belongs in this repository.**

## Supported pattern

1. HAL creates a unique remote-client identity locally.
2. The owner receives that client's credential through the local secure setup path.
3. The credential is entered directly into the external agent's connector UI or local secret store.
4. The agent initializes MCP and sees only the tools/scopes HAL grants.
5. Agent work is tied to canonical HAL project/task/delegation IDs.
6. Results return to HAL with receipts/evidence.

## Current target clients

- Grok custom MCP connector
- ChatGPT / Codex HAL Team Mesh plugin (OAuth path in development)
- Muse
- Claude/local MCP-capable clients
- future MCP-compatible agents

## Security rules

- Never commit bearer tokens, API keys, OAuth access tokens, OTPs, or recovery codes.
- Each external agent gets its own client identity.
- Revoke one client without rotating every other client.
- No agent may release blocked work, deploy, publish, spend, or mutate accounts unless HAL policy and explicit approval permit it.
- Public connector examples use placeholders only.
- HAL WorkGraph / EventStore / Supervisor remain canonical.
