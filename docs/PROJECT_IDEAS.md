# HAL SUPREME Public Project Ideas

These are deliberately scoped so contributors can help without access to private production credentials or the internal HAL runtime.

## Good first tasks

1. **Holographic UI accessibility audit**
   - Review public screenshots/pages for contrast, focus visibility, readable type sizes, and reduced-motion behavior.
   - Deliverable: issue with screenshots and specific CSS/UX recommendations.

2. **Mobile navigation QA matrix**
   - Test public routes at common mobile widths.
   - Deliverable: reproducible table of overflow, keyboard, focus, and layout findings.

3. **Community docs link checker**
   - Add a lightweight checker for internal Markdown links and public HAL URLs.
   - Deliverable: script/test plus documentation.

4. **Peer-join troubleshooting guide**
   - Expand common OpenAI-compatible client errors without publishing real credentials.

5. **MCP example pack**
   - Add sanitized example configurations for common clients using placeholders only.

6. **Public demo smoke tests**
   - Build deterministic tests that confirm public demo pages load and key controls remain present.

7. **Creator metadata schema review**
   - Propose a small public schema for artist, track title, artwork, credits, rights attestation, and remix permissions.

8. **Attribution component prototype**
   - Create a static UI prototype showing original work -> remix -> derivative lineage.

## Standard contributions

9. **Holographic status-card component**
   - Prototype an accessible, lightweight status card for task owner, state, progress, warnings, and receipts.
   - Must include reduced-motion mode.

10. **Operations timeline prototype**
    - Static/public mockup showing queued -> running -> testing -> review -> done/failed with evidence.

11. **System graph demo**
    - Build a demo graph from synthetic data showing service health and dependencies without exposing production topology/secrets.

12. **Community Music submission UX prototype**
    - Design the upload/metadata/rights/moderation flow using synthetic assets.

13. **Project Room activity-feed prototype**
    - Demonstrate comments, assets, tasks, reviews, contributor credits, and version history.

14. **Contribution provenance format**
    - Define a JSON format for contribution ID, source, author handle, license/permission, review state, accepted artifact hash, and related issue/PR.

15. **Agent interoperability example**
    - Show a safe OpenAI-compatible or MCP integration using public HAL endpoints/documentation and placeholder tokens.

16. **Eval fixture contribution**
    - Add public test prompts/expected contracts for mode behavior, tool boundaries, or response formatting.

17. **Creator accessibility pack**
    - Document captions, alt text, waveform/transcript, flashing-motion, and color-contrast guidelines for HAL media submissions.

## Larger mentored projects

18. **Build Together contributor dashboard**
    - Public project/task discovery, contributor profiles, claim/request flow, accepted-work credit, and project changelog.

19. **Community Radio discovery layer**
    - Rights-aware track discovery, queue visibility, creator profiles, likes/saves, moderation state, and attribution.

20. **Collaborative content project rooms**
    - Project members/roles, asset versions, comments, tasks, review gates, credits, and release handoff.

21. **Public reliability laboratory**
    - Synthetic status dashboard and reproducible regression packs for HAL web/API behavior.

22. **Portable HAL gateway onboarding**
    - Improve Docker/self-host onboarding with automated preflight checks and clearer provider abstraction.

23. **Creator remix/provenance graph**
    - Rights-aware source -> derivative graph with opt-in permissions and persistent attribution.

24. **Community challenge framework**
    - Periodic themed challenges for docs, UI, evaluations, media, or interoperability with transparent judging criteria and no hidden production access.

25. **Contributor analytics (privacy-preserving)**
    - Measure onboarding and retention from public GitHub events without tracking sensitive personal data.

## Research tasks

26. Compare open-source contributor onboarding across five successful AI/data projects.
27. Map public agent interoperability standards and where HAL can provide useful examples.
28. Evaluate accessible real-time collaboration UI patterns.
29. Survey creator-rights metadata standards applicable to remix/provenance.
30. Map no-cost/open compute programs suitable for public demo infrastructure.

## How to propose another project

Open an issue containing:
- problem;
- user/contributor benefit;
- public-safe scope;
- acceptance criteria;
- expected files/artifacts;
- dependencies;
- security/privacy considerations;
- suggested difficulty.
