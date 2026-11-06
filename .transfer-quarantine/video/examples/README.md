# OneShot product workflow GIFs

Ten distinct animated **product storyboards** in landscape video format (1600 × 900, 40 frames, four seconds, looping):

| GIF | Product moment | Visual treatment |
| --- | --- | --- |
| `workflow-style-01.gif` | Request | Assistant-led command screen |
| `workflow-style-02.gif` | Research | Repository evidence board |
| `workflow-style-03.gif` | Audit discovery | Finding radar and severity panel |
| `workflow-style-04.gif` | Planning | Light BuildSpecification canvas |
| `workflow-style-05.gif` | Fixture validation | Rejection, correction, recheck |
| `workflow-style-06.gif` | Host control | Security gate and receipt |
| `workflow-style-07.gif` | Build | Work preview and action rail |
| `workflow-style-08.gif` | Recovery | Checkpoint timeline |
| `workflow-style-09.gif` | Build verification | Independent criteria board |
| `workflow-style-10.gif` | Delivery | Final result and artifact review |

## Evidence boundary

The supplied `OneShot_3min_scenarios.mp4` shows six **simulated browser workflows**. The older `video/example/` capture suite also labels its events as simulated. The real-backend reference screenshots there only show Research/Audit UI at an earlier commit. Local `scripts/doctor.py` reported that `MODEL_API_KEY` was not configured and `ONESHOT_STATE_ROOT` was blocked during this rebuild, so no current live provider run was captured.

These GIFs therefore illustrate the current five-stage workflow contract in `.agents/contracts/workflow.yaml`, with an example frontend audit inspired by the supplied video. They are not screenshots of a completed live Build. The depicted frontend patch, six acceptance checks, task artifacts, and successful outcome are **storyboard content**, not observed current-run evidence. Every GIF states its illustrative status on screen.

The five stages are Research → Audit discovery → Planning → Fixture validation → Build. Host admission and authorization are controls, not a sixth stage. Independent Build verification stays within Build. Labels use sentence case. The generated assistant graphic is stored in `video/assets/oneshot-assistant.png`; the delivered animations here are GIFs.

## Regenerate

```powershell
node video/examples/render-gifs.mjs
```

Append a scene number (`1` through `10`) to regenerate only that GIF. The renderer uses `web/node_modules/playwright` and an isolated Pillow encoder through `uv`; it creates no intermediate PNG frames. Source: `product-workflow.html`, `render-gifs.mjs`, `encode-gif.py`.
