# HAL SUPREME Community

**Public community hub** for [HAL SUPREME](https://halsupreme.com) — docs, peer join, MCP setup, Discussions, and good first issues.

HAL SUPREME is a community-friendly AI companion and creator stack. This repository is for **documentation, examples, onboarding, and discussion** — not the private product monorepo.

| | |
| --- | --- |
| Product | https://halsupreme.com |
| Public engineering portfolio | https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/PORTFOLIO.md |
| Contributor roadmap | https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/docs/COMMUNITY_ROADMAP.md |
| Work with HAL | https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/docs/WORK_WITH_HAL.md |
| Peer join | https://halsupreme.com/peers.html |
| API | https://api.halsupreme.com |
| Discussions | [GitHub Discussions](https://github.com/UniteAndCreateForLife/hal-supreme-community/discussions) |
| Discord | [https://discord.gg/GnufdBbyg](https://discord.gg/GnufdBbyg) |

## What HAL is

HAL SUPREME helps with search, creation, coding, tool use, multimodal workflows, and collaboration. Public engineering work currently focuses on durable AI agents, MCP/tool integrations, local/private AI, evidence and provenance, evaluation, and reproducible demos.

Modes include:

- **Fast** — quick answers and lightweight tasks
- **Build** — coding and project work
- **Expert** — deeper reasoning
- **Council** — multi-perspective deliberation

Capabilities include **search**, **images**, **sandbox**, **voice**, **MCP**, and **peers** (OpenAI-compatible federation).

## Join the community

1. Read the [public engineering portfolio](https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/PORTFOLIO.md) to see what is actually verified.
2. Read [docs/peer-join.md](docs/peer-join.md) and [docs/mcp-setup.md](docs/mcp-setup.md).
3. Open a [Discussion](https://github.com/UniteAndCreateForLife/hal-supreme-community/discussions) to ask questions, share a reproduction, or propose interoperability work.
4. Pick a [good first issue](https://github.com/UniteAndCreateForLife/hal-supreme-community/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) if you want to contribute docs or examples.
5. For deeper engineering contributions, use the main repo's [CONTRIBUTING.md](https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/CONTRIBUTING.md) and [community roadmap](https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/docs/COMMUNITY_ROADMAP.md).
6. Follow this repo's [CONTRIBUTING.md](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).
7. Join Discord: [https://discord.gg/GnufdBbyg](https://discord.gg/GnufdBbyg).

**Never paste gateway Bearer tokens, API keys, private paths, OTPs, hidden/system prompts, or confidential client data into Issues, Discussions, Discord, or PRs.**

## Ways to collaborate

### Contribute

Good contribution areas include:
- MCP interoperability and examples;
- first-run documentation;
- local/private AI setup;
- reproducibility checks;
- evaluation and evidence fixtures;
- peer/federation usability.

### Research / engineering collaboration

For agent reliability, evidence/citation validation, provider routing, provenance, multimodal production, or bounded automation work, start with the main HAL engineering repository:

https://github.com/UniteAndCreateForLife/HAL_SUPREME

### Paid engineering

HAL also takes bounded engineering engagements where the first milestone can be tested and reviewed.

See:
https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/docs/WORK_WITH_HAL.md

Do not post confidential commercial details publicly; use the contact route on https://halsupreme.com.

## Self-host

Run your own OpenAI-compatible **HAL Model Gateway** with Docker (cloud-first; no local Ollama required):

```bash
git clone https://github.com/UniteAndCreateForLife/hal-supreme-community.git
cd hal-supreme-community/docker/model-gateway
python3 prepare-context.py
cp .env.example .env   # add GROQ_API_KEY (or another remote) + optional HAL_GATEWAY_TOKEN
mkdir -p secrets && openssl rand -base64 32 > secrets/hal_gateway_token && chmod 600 secrets/hal_gateway_token
docker compose up --build -d
curl -fsS http://127.0.0.1:8767/health
```

Full guide: [docs/DOCKER_GATEWAY.md](docs/DOCKER_GATEWAY.md) · Pack: [docker/model-gateway/](docker/model-gateway/) · Site: https://halsupreme.com/self-host.html

## Docs in this repo

- [Peer join](docs/peer-join.md) — point OpenAI-compatible clients at HAL
- [MCP setup](docs/mcp-setup.md) — Cursor / Claude Desktop style config
- [Community hub](docs/community-hub.md) — themes and where to talk

## License

MIT — see [LICENSE](LICENSE).
