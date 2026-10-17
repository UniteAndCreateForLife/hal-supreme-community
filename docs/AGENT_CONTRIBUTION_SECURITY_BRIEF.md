# Security Brief: AI Agents, Public Contribution Tasks, and Context-Exfiltration Traps

**Date:** 2026-10-17  
**Scope:** Public, read-only case study and maintainer guidance  
**Canonical evidence:** https://github.com/UniteAndCreateForLife/HAL_SUPREME/blob/main/case-studies/AI_AGENT_BOUNTY_HONEYPOT_GUARD_2026-09-24.md

## Why this matters

AI coding agents increasingly read public issues, contributor guides, pull-request templates, and repository-local instruction files before making changes. Those files are therefore part of an agent's effective input surface.

A malicious or research-oriented repository can exploit that surface by asking an automated contributor to include hidden runtime context in a public artifact. Examples include requests for:

- system or developer prompts;
- startup/session instructions;
- local home or working-directory paths;
- token/resource budgets;
- other context supplied before the user's task began.

The dangerous pattern is not the phrase "system prompt" by itself. The risk appears when a contribution instruction asks the contributor to **reproduce its own hidden/session context** in a PR, metadata file, issue response, or other public submission.

## Public HAL case study

HAL's public Agent Bounty Guard work documented one such pattern in a public bounty repository and built a read-only detector around the request semantics rather than around field names.

Measured public results reported by the canonical case study:

| Measurement | Public result |
| --- | ---: |
| Target issues blocked | 183 / 184 |
| Previous keyword-list matches on those issues | 118 / 184 |
| Legitimate system-prompt issues producing guard findings | 0 / 90 |
| Control repositories | 14 repos / 56 docs / 0 findings |
| Focused unit tests | 12 passed (30 sub-cases) |
| Targeted detector mutations caught by tests | 14 / 14 |

The target-set result is **in-sample** because the rules were refined while reading the target issues. The separate control repositories and 90 legitimate issues are the more useful false-positive evidence.

Full methodology, target details, limits, and machine receipt remain in the canonical HAL case study linked above.

## Why keyword blocking fails

A static keyword list is weak in both directions.

### False negatives

Attackers can rotate field names while keeping the request unchanged:

- `boot_context`
- `session_init`
- `initial_directives`
- `platform_config`
- other arbitrary labels

The semantic request—"put the context you started with into the submission"—is the invariant.

### False positives

Legitimate engineering issues frequently discuss:

- system prompts;
- prompt settings;
- SDK prompt behavior;
- configuration messages;
- model instructions.

Blocking the term itself discards valid AI-product work.

A safer detector looks for a **request addressed to the contributor** to reproduce **the contributor's own hidden/session material** in **a submission artifact**.

## Additional input-channel risks

The same public contribution surface can contain:

- HTML comments that tell automated systems to ignore visible warnings;
- invisible Unicode tag text;
- zero-width character runs;
- requests for local environment disclosure;
- misleading payment/reward language;
- repository-local agent instruction files that conflict with operator policy.

No single detector closes this class of risk.

## Structural controls are more important than detection

A safe contribution system should enforce these invariants even if every content detector fails.

### 1. Never serialize hidden runtime context into artifacts

The agent should not have a tool or helper that can blindly copy:

- system/developer messages;
- hidden memory/context;
- environment secrets;
- credential material;
- unrelated local paths

into a PR, issue, patch, attachment, or public response.

### 2. Treat repository instructions as untrusted input

Repository-local instructions can guide implementation but must not override:

- system/operator policy;
- credential boundaries;
- privacy boundaries;
- public-action approval requirements.

### 3. Isolate untrusted contribution work

Unknown repositories should be built/tested in an isolated environment with:

- no user secrets;
- no host home-directory mount;
- minimal network access;
- bounded CPU/memory/process limits;
- disposable workspace.

### 4. Require explicit authority for public actions

An agent can prepare a patch or draft, but publishing in the operator's name should remain governed.

Examples:

- opening a PR;
- posting a public comment;
- claiming a bounty;
- accepting terms;
- publishing media;
- spending funds.

### 5. Preserve evidence

When a task is rejected or blocked, record:

- source URL/document;
- matched rule;
- bounded excerpt;
- detector version;
- decision;
- timestamp.

Do not record the hidden context that the malicious task requested.

## Maintainer-side recommendations

Maintainers accepting AI-assisted contributions can reduce accidental secret leakage by:

1. keeping contributor instructions explicit and human-readable;
2. avoiding hidden instructions targeted only at automated contributors;
3. never requesting contributors' prompts, local paths, or hidden session data;
4. documenting whether AI assistance is permitted;
5. reviewing machine-generated metadata before making it a submission requirement;
6. providing a security-reporting route for suspicious contribution instructions;
7. testing contribution templates with both human and agent workflows.

## Agent-platform recommendations

Agent frameworks can add defense in depth by:

- separating untrusted repository text from trusted policy;
- tagging input provenance;
- preventing hidden-context export by construction;
- requiring confirmation before public mutations;
- sandboxing unknown code;
- scanning contribution instructions before handing them to an autonomous worker;
- including adversarial repository fixtures in regression suites.

## Open questions for security communities

This case suggests several areas where shared guidance or standards could help:

- a common threat taxonomy for agent-targeted contribution instructions;
- provenance labels for trusted vs repository-supplied instructions;
- standard "do not export hidden context" agent invariants;
- safe schemas for AI contribution metadata;
- benchmark fixtures for prompt/context-exfiltration attempts;
- recommended sandbox profiles for autonomous OSS contributors;
- maintainer guidance for accepting agent-generated PRs.

## Reproduce the public tool

Agent Bounty Guard source:
https://github.com/UniteAndCreateForLife/HAL_SUPREME/tree/main/examples/agent_bounty_guard

Public static demo:
https://huggingface.co/spaces/uniteandcreateforlife/agent-bounty-guard

The tool is read-only and dependency-free in its Python implementation. A JavaScript port is held to shared parity fixtures.

## Limits

- heuristic;
- English-only;
- issue comments are not part of the original scanner scope;
- Markdown/text scanning will not detect every image/CSS-based hiding technique;
- clean output means "no known pattern detected," not "safe";
- the public target-set score is not an independent benchmark.

The intended contribution to the broader security community is the **threat model, reproducible guard, test approach, and structural controls**, not a claim that one heuristic solves agent security.
