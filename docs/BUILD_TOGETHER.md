# Build Together with HAL SUPREME

HAL SUPREME is being developed as a network of people, tools, agents, creator workflows, and interoperable systems. This document is the public entry point for helping without requiring access to private runtime data or the internal monorepo.

## Contribution principles

1. **Small, reviewable work wins.** Prefer a bounded task with a testable result over a large rewrite.
2. **Evidence over claims.** Include screenshots, test output, reproduction steps, benchmarks, or other evidence appropriate to the contribution.
3. **No secrets.** Never post API keys, Bearer tokens, private paths, confidential client data, hidden/system prompts, or personal credentials.
4. **Untrusted code stays isolated.** External code and generated artifacts must be reviewed and tested in a sandbox before they can influence production HAL.
5. **Attribution matters.** Accepted contributors should receive visible credit in the project history/changelog.
6. **HAL remains governed.** Public contributions can propose and improve work; deployment, publishing, spending, account changes, or destructive actions stay behind owner review.

## Ways to help

### 1. Holographic interface and UX

Help evolve the HAL SUPREME website toward a readable holographic operations interface:
- accessibility and contrast audits;
- reduced-motion alternatives;
- responsive layout checks;
- information-dense task/agent cards;
- system graph and telemetry concepts;
- Music Queue / Radio / Team Room interface polish;
- SVG/CSS motion prototypes that remain lightweight.

### 2. Reliability and evaluation

Contribute reproducible evals for:
- chat mode behavior (Fast / Build / Expert / Council);
- provider routing and failover;
- tool-use correctness;
- API response contracts;
- accessibility;
- reconnect/retry behavior;
- deterministic regression fixtures;
- documentation smoke tests.

### 3. Creator and media workflows

Help with safe, rights-aware creator tooling:
- community music submission UX;
- metadata validation;
- attribution and provenance;
- remix permission models;
- audio/video QA fixtures;
- media accessibility;
- playlist/radio discovery concepts;
- creator profile and project-room prototypes.

### 4. Interoperability

Useful integration examples include:
- OpenAI-compatible clients;
- MCP;
- A2A / agent discovery concepts;
- LangGraph, CrewAI, AutoGen, and similar agent frameworks;
- webhook/event adapters;
- local/private inference;
- reproducible Docker examples.

Do not submit real provider credentials. Examples must use placeholders.

### 5. Community and documentation

We need:
- onboarding improvements;
- tutorials;
- translations;
- screenshots and walkthroughs;
- newcomer FAQs;
- architecture explainers;
- demo videos;
- accessibility checks;
- community moderation/documentation improvements.

### 6. Research and ecosystem mapping

Help us evaluate:
- open-source AI communities;
- contributor programs;
- hackathons;
- fiscal hosts and funding programs;
- creator networks;
- interoperability standards;
- public datasets/evals;
- free/open compute options.

Research contributions should include source links and the date checked.

## How work should flow

1. Pick or propose a bounded issue.
2. Comment with the part you want to take.
3. Agree on acceptance criteria before doing large work.
4. Submit a PR or artifact with evidence.
5. Review focuses on correctness, safety, maintainability, and whether the work fits HAL's existing architecture.
6. Accepted contributions are merged and credited.

## Contribution sizes

### Good first task
Usually documentation, accessibility, reproducibility, testing, examples, or small UI improvements.

### Standard contribution
A bounded feature, adapter, evaluation set, creator workflow slice, or tested UX improvement.

### Project
A multi-week effort with milestones, an explicit owner/mentor, acceptance criteria, and a written integration plan.

## Public project areas

- HAL web experience and holographic operations UX
- Community Music / Radio
- Build Together project rooms
- Contributor and bounty UX
- Agent/tool interoperability examples
- Reliability and evaluation
- Local/private AI
- Creator rights, attribution, and provenance
- Public demos and educational material

See [PROJECT_IDEAS.md](PROJECT_IDEAS.md) for concrete work packages.

## Communication

Use GitHub Issues/PRs for work that needs a durable engineering record. Use Discussions or Discord for exploration and community conversation.

- Discussions: https://github.com/UniteAndCreateForLife/hal-supreme-community/discussions
- Discord: https://discord.gg/GnufdBbyg
- Product: https://halsupreme.com

## Security boundary

Do not test security issues against production users or disclose exploit details publicly. Follow [../SECURITY.md](../SECURITY.md) for vulnerability reporting.
