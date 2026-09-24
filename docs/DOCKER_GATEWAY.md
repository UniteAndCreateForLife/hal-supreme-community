# HAL Model Gateway — Docker self-host

Run an OpenAI-compatible **HAL Model Gateway** with Docker. Cloud-first routing is on by default (no local Ollama required inside the image).

- Product: https://halsupreme.com
- Self-host page: https://halsupreme.com/self-host.html
- Peers: https://halsupreme.com/peers.html
- Discord: https://discord.gg/GnufdBbyg
- Pack path in this repo: [`docker/model-gateway/`](../docker/model-gateway/)

---

## What you get

- OpenAI-compatible API: `/v1/models`, `/v1/chat/completions`, `/health`, peers, tools
- Cloud-first routing (`HAL_CLOUD_FIRST=1`)
- Auth via **env** or **secret file** (never baked into the image)
- Optional Piper voices via volume
- Slim build context under `docker/model-gateway/context/`

---

## One-liner

```bash
git clone https://github.com/UniteAndCreateForLife/hal-supreme-community.git
cd hal-supreme-community/docker/model-gateway
python3 prepare-context.py
cp .env.example .env
# edit .env — add at least one remote key (e.g. GROQ_API_KEY)
mkdir -p secrets
openssl rand -base64 32 > secrets/hal_gateway_token && chmod 600 secrets/hal_gateway_token
docker compose up --build -d
curl -fsS http://127.0.0.1:8767/health
```

Default **host port `8767`**.

Windows (PowerShell):

```powershell
cd docker\model-gateway
python .\prepare-context.py
copy .\.env.example .\.env
# create secrets\hal_gateway_token (random 32+ bytes) OR set HAL_GATEWAY_TOKEN in .env
docker compose up --build -d
curl.exe http://127.0.0.1:8767/health
```

---

## Layout

| Path | Role |
| --- | --- |
| `docker/model-gateway/Dockerfile` | Slim Python 3.12 image (amd64 + arm64) |
| `docker/model-gateway/docker-compose.yml` | Service, healthcheck, secrets |
| `docker/model-gateway/.env.example` | Required vars (no real secrets) |
| `docker/model-gateway/prepare-context.py` | Refresh `context/` from `HAL_ROOT` or keep shipped context |
| `docker/model-gateway/context/` | Clean build context |
| `docs/DOCKER_GATEWAY.md` | This runbook |

---

## Environment

| Var | Default | Notes |
| --- | --- | --- |
| `HAL_CLOUD_FIRST` | `1` | Prefer remote providers |
| `HAL_GATEWAY_TOKEN` | (empty) | Preferred auth; if empty, secret file is used |
| `HAL_GATEWAY_TOKEN_FILE` | `/run/secrets/hal_gateway_token` | Inside container |
| `HAL_GATEWAY_TOKEN_HOST_FILE` | `./secrets/hal_gateway_token` | Compose secret source on host |
| `HAL_GATEWAY_HOST_PORT` | `8767` | Host publish port |
| `HAL_PUBLIC_API_BASE` | `https://api.halsupreme.com` | Public API base used in generated links |
| `GROQ_API_KEY` etc. | — | At least one remote key for cloud-first chat |

**Never** print or commit `secrets/hal_gateway_token` or `.env`.

---

## Start / stop / health

```bash
cd docker/model-gateway
docker compose up --build -d
docker compose ps
curl -fsS http://127.0.0.1:8767/health
docker compose logs -f --tail 100
docker compose down
```

Expected health JSON shape:

```json
{"status":"ok","service":"hal-model-gateway","voice":{"tts":true,"stt":false}}
```

`tts` is true only when Piper voices are mounted and a `piper` binary is available (optional). Chat works without TTS.

### Optional chat smoke (do not log the token)

```bash
TOKEN=$(tr -d '\r\n' < secrets/hal_gateway_token)
curl -fsS http://127.0.0.1:8767/v1/models -H "Authorization: Bearer $TOKEN"
curl -fsS http://127.0.0.1:8767/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"hal/fast","messages":[{"role":"user","content":"Say hi in 5 words"}],"max_tokens":32}'
```

---

## Oracle Always Free ARM (Ampere A1) notes

1. Create Ubuntu ARM VM (confirm current Always Free limits).
2. Open VCN for SSH + 443 (or SSH only and put Cloudflare/Caddy in front).
3. Install Docker Engine + Compose plugin.
4. Clone this repo; run the one-liner above.
5. Create `.env` with provider keys; create the token file **on the VM** (do not paste tokens into chat).
6. `python:3.12-slim-bookworm` is multi-arch — works on aarch64.
7. Piper is optional; cloud-first chat does not need it.
8. TLS: Caddy or Cloudflare tunnel → container `:8766`.
9. Heartbeat cron (`curl -fsS https://your-host/health`) so idle reclaim is less likely.

---

## Voices

Piper ONNX files are large and **not** in the image. Uncomment the voices volume in `docker-compose.yml` and point `HAL_VOICES_HOST_PATH` at your ONNX directory if you want TTS.

---

## Operator checklist

- [ ] `docker compose up --build -d` healthy on host `:8767`
- [ ] `GET /health` → `status=ok`
- [ ] Bearer `GET /v1/models` lists `hal/fast` etc.
- [ ] One `POST /v1/chat/completions` returns a reply when keys are present
- [ ] Secrets only in `.env` / secret file / vault — not in git

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Compose fails on secret file | Create `./secrets/hal_gateway_token` or set `HAL_GATEWAY_TOKEN` in `.env` plus a dummy secret file |
| Chat 401 | Token mismatch between client and container |
| Chat empty / providers fail | Set at least `GROQ_API_KEY` (or another remote) in `.env` |
| Huge image | Ensure build context is `./context`, not a full monorepo root |

## Security

Never paste gateway Bearer tokens, API keys, or private paths into Issues, Discussions, Discord, or PRs.