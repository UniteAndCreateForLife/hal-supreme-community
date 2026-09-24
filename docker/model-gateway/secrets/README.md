# Secrets (gitignored)

Create `hal_gateway_token` here (never commit it):

```bash
mkdir -p secrets
openssl rand -base64 32 > secrets/hal_gateway_token
chmod 600 secrets/hal_gateway_token
```

Or set `HAL_GATEWAY_TOKEN` in `.env` and keep a dummy file at this path so Compose can mount the secret.
