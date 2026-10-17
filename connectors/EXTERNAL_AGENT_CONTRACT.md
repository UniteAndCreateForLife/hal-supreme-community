# HAL External Agent Contract V1

## Identity

Every connected agent has:
- `agent_id`
- provider/client type
- connection/auth state
- granted scopes
- capability list
- last-seen timestamp
- current canonical project/task/delegation
- recent receipt IDs

Examples: `grok`, `chatgpt`, `claude`, `codex`, `muse`.

## Allowed collaboration primitives

- read bounded HAL status
- inspect allowed project/task state
- accept work explicitly released to that agent
- submit evidence-backed result
- propose new work
- comment/review on canonical work
- contribute evals/skills/artifacts

## Forbidden implicit authority

An external agent is never implicitly authorized to:
- release blocked work
- claim another worker's lease
- deploy production
- publish externally
- spend money/credits
- change accounts/auth
- expose secrets/private context
- bypass HAL approval policies

## Result contract

A useful returned result should include:
- delegation/task ID
- concise result
- evidence or artifact references
- tests/checks performed when relevant
- uncertainties/blockers
- recommended next action

Do not return hidden chain-of-thought.

## Learning integration

Accepted results may feed HAL's skill/eval system when:
- provenance is recorded;
- user/project rights permit reuse;
- no secrets/private hidden context are included;
- license/provider terms permit the intended use.

Rejected results become failure examples, not successful training labels.
