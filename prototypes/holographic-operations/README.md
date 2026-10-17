# HAL Unified Holographic Workspace prototype

Public-safe reference implementation for the HAL SUPREME GUI direction.

## What it demonstrates

- holographic / retro-digital visual language;
- one compact workspace rail spanning Chat, Operations, Media, Radio, Team, Build Together, Bounties, Graph, Apps, Lab, and Settings;
- global search/command surface and current-project context;
- Operations Center task visibility;
- synthetic health telemetry;
- Music/Video ownership states;
- native App Dock with Muse, GitHub, Google Workspace, Cloudflare, Hugging Face, Livepeer, YouTube/OBS, and HAL Android examples;
- permission/capability indicators and governed actions;
- Build Together contributor tasks;
- owner approval queue;
- System Graph;
- seamless cross-system workflow examples;
- evidence-first operational transparency.

## Important boundary

All data in this prototype is synthetic or public. It does not read production HAL state, expose private chain-of-thought, or carry deployment authority.

The production implementation should map these visual components onto HAL's canonical WorkGraph / EventStore / Supervisor / receipt surfaces rather than creating a second task store. External apps should use structured API/MCP/plugin routes where possible, with permissioned UI control only as a bounded fallback.

## Accessibility

- keyboard focus states;
- responsive layouts;
- state labels are not color-only;
- `prefers-reduced-motion` disables animation;
- no external fonts, trackers, scripts, or dependencies.

## Related public tasks

- #16 Holographic UI accessibility audit
- #17 Accessible holographic status card
- #20 Synthetic HAL operations timeline
- #31 Public-safe HAL System Graph
- #32 Build Together contributor dashboard
- #33 Rights-aware Community Radio discovery

Open `index.html` directly in a browser to view the prototype.
