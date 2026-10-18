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

## Local validation

From the repository root, install the validation dependencies in a Python 3.10+
virtual environment, then validate every recipe against the bundled Draft
2020-12 schema:

```bash
python -m pip install -r tools/requirements-validation.txt
python tools/validate_automation_recipes.py
python -m unittest discover -s tests -v
```

Dependency installation requires network access. Validation and tests run
offline: they read local JSON and never execute recipe actions or contact HAL.
The validator scans `automation-recipes/**/*.json`, excluding only
`schema/automation-recipe-v1.schema.json`. It reports filenames and JSON paths
for schema errors and exits with status 1 for invalid JSON, schema violations,
missing/empty recipe directories, or an unreadable/invalid schema. Success exits
with status 0 and the number of validated recipes. External schema references
are not fetched.

For a separate directory of candidate recipes, use
`python tools/validate_automation_recipes.py --recipes-dir path/to/recipes`.
It still uses the repository's bundled schema. Synthetic invalid test fixtures
live under `tests/fixtures/`, outside the default scan.

This checks the schema's structural constraints, not authorization, credential
absence, or whether an automation is safe to run. Owner review remains required.

## Migration model

External scheduler migration should use:

`IMPORTED -> SHADOW -> CANARY -> TAKEOVER_READY -> HAL_OWNED`

The source scheduler remains active until HAL proves equivalent trigger/result behavior and the owner approves cutover.

## Security

Do not put passwords, API keys, OAuth secrets, OTPs, recovery codes, payment details, private paths, hidden prompts, or private user data in a recipe.

Public contributions should use synthetic filters and placeholder identifiers only.
