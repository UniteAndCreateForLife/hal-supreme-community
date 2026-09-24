# HAL Model Gateway (Docker)

One-click **OpenAI-compatible** model gateway for [HAL SUPREME](https://halsupreme.com).

Full runbook: **[docs/DOCKER_GATEWAY.md](../../docs/DOCKER_GATEWAY.md)**

## Quick start

```bash
cd docker/model-gateway
python3 prepare-context.py
cp .env.example .env         # add at least one provider key (e.g. GROQ_API_KEY)
mkdir -p secrets
openssl rand -base64 32 > secrets/hal_gateway_token && chmod 600 secrets/hal_gateway_token
docker compose up --build -d
curl -fsS http://127.0.0.1:8767/health
```

Default host port **8767**. Auth: Bearer token from `HAL_GATEWAY_TOKEN` or the secret file.

**Never commit `.env`, `secrets/hal_gateway_token`, or real API keys.**

## Join the mesh

- Self-host: https://halsupreme.com/self-host.html
- Peers: https://halsupreme.com/peers.html
- Discord: https://discord.gg/GnufdBbyg