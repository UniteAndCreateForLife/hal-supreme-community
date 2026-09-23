# Contributing to HAL SUPREME Community

Thanks for helping HAL SUPREME grow as a **free, community-led** project. This repo is for **docs, examples, and safe website-join slices** — not the full private HAL monorepo.

| | |
| --- | --- |
| Live product | https://halsupreme.com |
| Peer join | https://halsupreme.com/peers.html |
| API | https://api.halsupreme.com |

## Code of conduct

Be respectful. No harassment, hate, or doxxing. No posting secrets, tokens, or other people's private data. Moderators may remove content and ban accounts that break this. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## What you can contribute (v1)

- Documentation clarity (peer join, MCP setup, federation overview)
- Examples: curl, OpenAI-compat JSON blocks, MCP `mcp.json` templates (**placeholders only**)
- Website-slice polish: copy, accessibility, broken links on static join pages
- Typos, issue templates, Discussion prompts
- Repro notes for **public** product bugs (UI), filed as issues

## What is out of scope (do not PR here)

- Gateway auth bypasses, rate-limit circumvention, or exploit PoCs
- Provider API keys, Cloudflare tokens, Discord bot tokens, or any real secrets
- Full BRAIN / autonomy / ops / internal control-plane code
- Demands for free unlimited API access

## Getting started (no monorepo required)

1. Fork or clone this public community repo.
2. Edit Markdown or static HTML examples locally.
3. Open a small PR with a clear description and screenshots if UI-related.
4. Link a related Discord `#dev` thread if useful (when Discord invite is published).

## Peer / API access

Chat, models, and `GET /v1/peers` require a **Bearer token** issued by maintainers. There is **no** anonymous public completions endpoint for growth. Never commit a real token; use `<HAL_GATEWAY_TOKEN>`.

Never paste tokens in Discord, Issues, Discussions, or PRs.

### MCP (local)

Example shape (adjust for your machine; do not hard-code personal absolute paths):

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

See [docs/mcp-setup.md](docs/mcp-setup.md) for notes on public vs local gateway.

## Good first issues

Look for the label `good first issue`. Typical starters:

1. Improve peer-join wording for first-time OpenAI-compat users
2. Add a copy-paste curl block for `GET /health` and `GET /v1/models`
3. Fix accessibility (contrast, alt text) on static community pages
4. Add a "Troubleshooting 401 on /v1/peers" FAQ section
5. Normalize example JSON for copy-paste tools

## PR checklist

- [ ] No secrets or real tokens
- [ ] No absolute personal filesystem paths
- [ ] One concern per PR
- [ ] Docs tested by reading them aloud / following steps on a clean machine when possible
- [ ] Related issue linked (if any)

## Security

If you find a vulnerability in the **live** product or gateway, **do not** open a public issue with exploit details. Follow [SECURITY.md](SECURITY.md).

## License

Contributions are under the MIT License — see [LICENSE](LICENSE).
