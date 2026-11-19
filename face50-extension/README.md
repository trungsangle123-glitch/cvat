# face50-extension — CVAT auto-label for Facial Landmark-50

Chrome MV3 extension that pre-labels the 7 Facial Landmark-50 skeletons (50
points) on a CVAT job. It reads the current frame from the CVAT canvas, sends it
to your own model container, and writes the result back through CVAT's REST API
using the page's session — no CVAT plugin or server access needed.

Pairs with `../face50-server` (default endpoint `http://localhost:58219/predict`).

## Install

1. Start the model container (see `../face50-server/README.md`) and check
   `http://localhost:58219/health`.
2. `chrome://extensions` → enable *Developer mode* → *Load unpacked* → pick this
   folder.
3. Click the extension icon → options page:
   - **Endpoint**: `http://localhost:58219/predict`
   - **Test connection** should report the backend (e.g. `mediapipe-facemesh`,
     or `insightface-2d106` if you enabled that server backend).
4. Add the 7 labels to the task (one time):
   - copy the JSON from the options page, or run
     `python ../face50-server/tools/setup_task.py --task-id N --apply`;
   - the job must show skeletons `longmaytrai`, `longmayphai`, `songmui`,
     `mattrai`, `matphai`, `moingoai`, `moitrong` with sublabels `p0` … `p49`.
5. Open the job (`/tasks/N/jobs/M`) and reload the page. The **Face-50** panel
   appears bottom-left; drag its header to move it.

If the labels are missing or incomplete, the panel says so instead of writing
shapes that CVAT would reject.

## Panel

| control | what it does |
| --- | --- |
| **Auto-label** (`Alt+F`) | predict the current frame and write the 7 skeletons |
| **Preview** | show the points on the overlay, do not write |
| **Replace** | delete the 7 Face-50 skeletons of this frame before writing (otherwise a second click adds duplicates) |
| **IDs** | draw point ids on the overlay |
| group checkboxes | which of the 7 skeletons to write |
| **All frames** + range | loop over a frame range; **Stop** interrupts. Batch always writes (Preview does not apply) |
| **Save** | click CVAT's own "Save" (top bar). Only needed for edits you made in CVAT itself — auto-labelled shapes are already stored |
| **Reload** | reload the annotator at the current frame |
| **Clear** | clear the overlay only |

Overlay colours follow the guideline: green = visible, orange = occluded, red =
outside. Settings (endpoint, timeout, toggles, groups) are stored in
`chrome.storage.local` and shared with the options page.

Writes go straight to `PATCH /api/jobs/{id}/annotations/?action=create`, so you
do not need to press CVAT's Save for these shapes — but any edits CVAT itself
has not saved are unaffected by this extension.

## Frame order / batching

The batch loop fetches frames with
`GET /api/jobs/{id}/data/?type=frame&number=N&quality=original`, so it does not
depend on the player UI. It does not change the frame you are looking at.

Guideline consequences baked into the flow:

- no face in a frame → the frame is skipped and reported as an error in the
  batch summary ("skip it" is the rule, not "annotate nothing");
- several faces → the model picks the largest (assumed driver);
- a skeleton whose visible points fall below the group threshold is written
  entirely as Outside;
- every frame still needs a human review — this is a pre-label, not a finished
  annotation.

## Files

| file | role |
| --- | --- |
| `manifest.json` | MV3 manifest; matches `https://cvat.edufun.ai/*` |
| `background.js` | service worker; POSTs frames to the model (CORS-free) and `/health` pings |
| `content.js` | panel, frame capture, prediction, shape building, REST write, overlay, batch |
| `options.html` / `options.js` | settings + labels JSON |
| `labels_raw.json` | packaged copy of `face50-server/labels_raw.json` |

## Use on another CVAT instance

Edit `manifest.json`:

```json
"host_permissions": ["https://your-cvat.example/*", "http://localhost/*"],
"content_scripts": [{"matches": ["https://your-cvat.example/*"], ...}]
```

then reload the unpacked extension. Same-origin REST calls use the page session,
so the extension has no credentials of its own.

## Troubleshooting

| symptom | cause |
| --- | --- |
| "CVAT canvas not found" | not on a 2D job page, or the frame has not rendered yet |
| "Cannot reach …/health" | container not running, or wrong host port in the endpoint |
| "This job has no Face-50 skeleton labels" | step 4 was skipped, or the labels are on the project while the task has its own set |
| "CVAT rejected the shapes (HTTP 400/403)" | sublabel ids do not map to `p0`…`p49`, or the session/CSRF cookie is stale — reload CVAT |
| duplicates after re-running | enable **Replace**, or use **Preview** while iterating |
| model returns `detected: false` | no face, frame too small, or a heavy profile view |
