# OneShot — Interactive HTML Demo & Capture Suite

**Location:** `video/example/` · **Current source commit:** `3d2f3190c89d83ac1e3516199eb884de2f19e0f6` (branch `main`)  
**Reference-frame source commit:** `d10ae4dc6b4b539ca43586dbeaf86c894591e3f8`

## Evidence classification (read first)

| Artifact | Classification |
|---|---|
| `screenshots/reference/*.png` | **REAL, HISTORICAL** captures of the API-backed OneShot `live.html` UI at reference commit `d10ae4d`, taken against the then-live backend before the demo was built. They are not current-HEAD backend evidence. Later commits added a separate React connector modal; `live.html` itself is unchanged between the two commits checked here. |
| `index.html` demo workflow (chat, stages, artifacts, Connection settings) | **SIMULATED** deterministic fixtures rendered in-browser by `demo.js`. Every page shows a `SIMULATED` badge; the demo never calls the real backend. The two-section Connection settings dialog visually mirrors the current React source at `3d2f319`, but its outcomes are simulated and are **not** a current-HEAD backend execution capture. |
| `screenshots/scenario-*/`, `recordings/*.webm`, `traces/*.zip` | **REAL** Chromium browser pixels/video/traces captured by Playwright while driving the simulated demo above. |
| Muse Image 1.0 artwork / Cosmos 3 motion | **Not used** (optional per spec; marked `not checked` in `verification.json`). |

The exact changed-file list is available from Git because the whole deliverable is untracked:

```powershell
git status --short -- video
git ls-files --others --exclude-standard -- video
```

## What this is

A working interactive reproduction of OneShot's existing UI — rail nav, topbar,
System Chat transcript, stage progress chips (Intake → Research → Audit →
Planning → Fixture Validation → Build Admission → Build → Verification),
Task Summary, PLAN TODOs, artifacts with a review modal, Evidence Stream, and
the current two-section Connection settings dialog — following the visual
language of `web/src/styles.css` and `web/public/live.html` (dark navy
`#060a18`, cyan `#52dcff`, robot/stage-card chat).

12 deterministic scenarios (75 actions, 55 screenshot checkpoints) play the
full governed workflow: startup → request → research evidence → audit →
planning/TODOs → fixture validation rejection + correction → host Build
Admission (default-deny) → tool-executing build → MCP/model connection errors
and recovery → interruption/recovery → independent verification → final
artifact review.

## Run it

```powershell
cd video/example
node serve.mjs            # http://127.0.0.1:8917 (PORT env overrides)
# open http://127.0.0.1:8917/index.html
```

Controls: scenario selector, **Play Scenario**, **Play All**, **Next Action**,
**Previous**, **Pause/Resume**, **Reset**. You can also type in the System Chat
composer and use the app manually — it is a working app, not a slideshow.
Deep-link any state: `index.html?scenario=S08&step=5`.

## Capture / verify (already executed; outputs committed to disk, not Git)

```powershell
node capture.mjs           # 55 checkpoint screenshots + 12 videos + 12 traces + capture_manifest.json
node verify-capture.mjs    # writes verification.json (dimensions, SHA-256, duplicates, secrets scan)
node ../../web/node_modules/@playwright/test/cli.js test -c playwright.config.js   # interactive spec suite
node reference-capture.mjs # re-capture the real backend UI into screenshots/reference/
```

Playwright/Chromium come from `../../web/node_modules` (`@playwright/test 1.58`)
— no extra install. Everything runs headless Chromium at 1920×1080.

## Layout

```
index.html  styles.css  demo.js        the interactive demo
scenarios.json                          12 scenarios / 75 deterministic actions
serve.mjs  capture.mjs  capture.spec.js  playwright.config.js  verify-capture.mjs
reference-capture.mjs                   real-backend UI reference capture
screenshots/reference/                  REAL live-app captures (visual reference)
screenshots/scenario-01..12/            REAL demo captures (checkpoint frames)
recordings/Sxx-recording.webm           REAL Chromium video per scenario
traces/Sxx-trace.zip                    REAL Playwright trace per scenario
capture_manifest.json                   per-shot action, URL, timestamp, SHA-256
storyboard.json                         180-second video storyboard (12 scenes)
verification.json                       independent verification report
```

Generated media is intentionally **not committed to Git** (per task
instructions) — it lives on disk under this directory. OneShot core source
(`agent/`, `web/`, host contracts) was not modified; the only new files are
under `video/example/`.

## Findings worth knowing (from inspection)

- The real `live.html` audit flow **works** against the live backend (task
  created, steps streamed, "Finished looking"). One upstream rendering bug is
  visible in `screenshots/reference/original-03-after-submit.png`:
  `undefined[object HTMLDivElement],[object HTMLDivElement]` leaks into the
  summary card. The demo reproduces the intended UI and does **not** replicate
  the bug; it is recorded here and in the upstream capture as evidence.
- Real React app flow proven by `web/tests/research.spec.js`:
  submit → `awaiting_mcp` → Run Research → `research_completed` →
  `_research.json` artifact. The demo mirrors these exact status strings.
