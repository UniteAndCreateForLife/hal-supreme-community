# HAL Automation Recipes

Public-safe example automations for the HAL Automation SDK.

These recipes demonstrate **intent, triggers, conditions, permissions, approval policy, idempotency, and expected receipts**. They do not contain credentials and do not grant permissions by themselves.

## Rules

- HAL WorkGraph / EventStore / Supervisor remain canonical.
- A recipe cannot create a second scheduler or task ledger.
- Connecting a provider and approving scopes is a separate user action.
- External/public/account/spend/destructive actions require explicit authority.
- Recipes should prefer event-driven triggers over frequent polling where practical.
- Every mutating action must be idempotent and receipt-backed.
- A NO_CHANGE run is a valid outcome and should remain quiet unless the user requests otherwise.

## Included recipes

- `community-growth-daily.json` — a daily evidence-based community-growth pass.
- `partner-reply-watch.json` — a generic meaningful-reply watch for selected email threads/senders.
- `website-regression-watch.json` — a read-only website health/regression watch that proposes repair work instead of silently mutating production.

## Migration model

External scheduler migration should use:

`IMPORTED -> SHADOW -> CANARY -> TAKEOVER_READY -> HAL_OWNED`

The source scheduler remains active until HAL proves equivalent trigger/result behavior and the owner approves cutover.

## Security

Do not put passwords, API keys, OAuth secrets, OTPs, recovery codes, payment details, private paths, hidden prompts, or private user data in a recipe.

Public contributions should use synthetic filters and placeholder identifiers only.
