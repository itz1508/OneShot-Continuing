# OneShot-Continuing — video evidence and visual production

**One-line summary:** Use the actual OneShot-Continuing application as the video source; keep synthetic visualization and promotional robot art separate from verified E2E demonstrations. The reusable `video_toolkit` can prepare and assemble media but does not drive the OneShot host.

## Authority and provenance

- **Working repository:** [`itz1508/OneShot-Continuing`](https://github.com/itz1508/OneShot-Continuing). Read `CONTINUATION.md` first. This is a detached, independent continuation; `itz1508/OneShot` and its Hackathon submission remain frozen.
- **Imported baseline:** `OneShot` commit `78162220d545f04206a940c38e33adc031d96f2d`, documented in `CONTINUATION.md`. New continuation work starts *after* that import; report exact qualifying commits for any new feature.
- **Actual frontend behavior:** `web/src/main.jsx` and `web/src/styles.css`, rendered against the running app's real backend. Browser results and event/receipt records take precedence over optimistic UI claims.
- **Existing Audit-specific visual reference:** `web/public/live.html`. This is an Audit screen with real API routes when a corresponding host is running; it is **not** a full-stage Research→Build→Verification implementation.
- **Existing synthetic multi-role visualizer:** `web/public/demo.html`, `web/tests/demo.spec.js`, and `web/demo/capture.py`. It intentionally makes zero real API or MCP calls. Its tests prove projection/animation only, **not production E2E**.
- **Additional illustrations and static previews:** may guide optional design, never override exact running UI screenshots or establish a working feature.

When these disagree, use the target **working revision's actual source and running behavior**. If a screenshot is supplied as the exact target, first reproduce it in Chromium and compare the pixels and layout. Do not invent a new dashboard, copy a random thumbnail, or redesign without authorization.

## Agent workflow (strict, before capture)

```text
Accepted request + intended audience + duration + freeze policy
  ↓
Research: existing repo, rights, real features, source revision, event contracts
  ↓
Audit Discovery: run application; inspect screenshots, scripts, CSS, backend,
                 workflows, events, real controls, current failures (read-only)
  ↓
Planner: shot list mapping FEATURE → UI ACTION → BACKEND EVENT → EVIDENCE → TIMECODE
  ↓
Gap/fixture validation: check reachable endpoints and example run end to end
  ↓
Build admission: authorize only the recording/editing work; preserve frozen source
  ↓
Browser recording: actual app + actual interaction, no fake event injection
  ↓
Video processing: inspect → prepare → shot plan → existing clips → assemble
  ↓
Independent verification: screenshots, timing, FFprobe, SHA-256, action/event proof
  ↓
Approved video or BLOCKED with evidence; no invented E2E result
```

**Do not start by making a cinematic graphic.** The implementation and screen geometry are inputs to the video, not invented output. Real browser capture tooling must exist separately; `video_toolkit` has no browser recorder, and `web/demo/capture.py` records **only** simulated `demo.html` scenarios.

## How the parts connect

```text
OneShot-Continuing git SHA ───► frontend & host/backend ───► actual task/run
                                              │                  │
                                             UI              SSE/events,
                                              │              files/receipts,
                                              │              tests/verification
                                              └────────┬─────────┘
                                                       ▼
                                      Chromium real interaction recording
                                                       │
                                      Clip + event/commit evidence manifest
                                                       │
ChatGPT Library /video_toolkit (separate source) ───► inspect + prepare
                                                       │
                                       Storyboard with source/evidence IDs
                                                       │
                                  recorded/approved clips/<shot-id>.mp4
                                                       │
                                  assemble (video-only) + inspect/FFprobe
                                                       │
                                      Visual/E2E acceptance or BLOCKED
```

Do not describe a running Vite frontend as proof of a connected API. For each claim (Research, Audit Discovery, Planning, Fixture Validation, Build Admission, Builder, independent verification), verify the exact host event, accepted revision, stage gate and receipt **where supported**. If not implemented or unreachable, mark the feature blocked or out of scope. Never synthesize receipt success, invent model calls, or claim a passing E2E run based on `demo.html`.

## Visual design, if a new interface is explicitly authorized

The desired concept is **not yet a verified implementation**: the robot stays visually anchored, with subtle blink/face changes and occasional natural talking/asking gestures; information flows in the **left** channel; the **right** changes work screens/pages, with recognizable pagination dots. Show only current-state data from the run: workstream, file actions, actual capability names and receipts. Use current `web/src/styles.css` navy/cyan tokens unless the user approves new tokens. Keep the UI readable at desktop `1440×900` and mobile `390×844` and preserve the single System Chat context. The center robot must not hop between unrelated layouts; no duplicated status panels, endless spinning, fake progress, or pagers that do not switch views.

To build this concept later, **Planner** must specify the actual layout/component/animation changes and verification fixtures before Builder implementation. Only after the real browser shows it may it appear in a working-product demo. Until then, creative illustrations may appear **only** as separately labeled concept artwork, never as screenshots of running OneShot.

## Recording and media commands

Run OneShot-Continuing's actual app using the repo instructions; capture with a separate authorized Chromium/Playwright recording path that observes real user actions and network/events. The repository does **not** currently contain a proven real-workflow capture script. `web/demo/capture.py` is synthetic-only; do not repurpose it by changing the label while keeping fake sources.

The reusable toolkit lives outside this repository at ChatGPT Library `/video_toolkit/`. It is not installed automatically. In an isolated environment, materialize/install that package according to its `README.md` and run:

```bash
video-toolkit doctor
video-toolkit inspect ./recordings/real-run.mp4
video-toolkit prepare ./recordings ./new-video-project
video-toolkit plan ./brief.json ./new-video-project/plan.json
# A separate recorder/editor must create ./new-video-project/clips/<shot-id>.mp4
video-toolkit assemble ./new-video-project/plan.json ./new-video-project/clips ./final.mp4
video-toolkit inspect ./final.mp4
```

`plan` does not automatically trim source recordings. `assemble` normalizes/concatenates existing clips and removes **all audio**. Use an external editor for narration/audio/subtitles, then re-probe and inspect final output. Cosmos clip generation is optional and GPU-only; for approved decorative assets it can produce motion but cannot verify or replace application features. No video is generated by `--dry-run`.

## Release review checklist

- [ ] Pin repository revision, original versus continuation feature list, commit evidence, and rights.
- [ ] Record actual UI actions and source-to-event/receipt mapping for each claimed feature.
- [ ] Verify the target UI against real browser screenshots at desktop/mobile viewports.
- [ ] Label simulation/illustration independently; never intermingle them with E2E evidence.
- [ ] Confirm every shot ID resolves to a playable clip with recorded or generated provenance.
- [ ] Probe final duration, resolution, fps, audio, and SHA-256; watch the complete video.
- [ ] Check legibility, truncation, paging dots, robot face/motion, screen transitions, and absence of `undefined` or fabricated statuses.
- [ ] Preserve any frozen Hackathon deliverable; do not push results back to `itz1508/OneShot`.

**Not currently verified:** a complete connected OneShot Research→Build E2E recording, the new proposed robot/pager layout, or NVIDIA Cosmos inference. These require future implementation/evidence and must never be reported as already complete.