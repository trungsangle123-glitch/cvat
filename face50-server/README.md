# face50-server — Facial Landmark-50 model service

FastAPI + MediaPipe service that turns a frame into the 7 skeletons / 50 points
defined by `Face_Landmark50_Annotation_Guideline_V1.docx`. The browser extension
(`face50-extension/`) POSTs frames here; nothing leaves your machine.

An optional InsightFace `2d106det` backend is available for frames where the
MediaPipe mesh struggles (profiles, older faces). It is off by default.

## What it returns

`POST /predict` with `{"image": "<base64 or data: URL>"}`:

```json
{
  "width": 1920, "height": 1080,
  "model": "mediapipe-facemesh",
  "faces_found": 1, "detected": true,
  "face": {"bbox": [x1, y1, x2, y2], "score": 0.97, "yaw_ratio": 0.04, "yaw_deg": 3.1},
  "skeletons": [
    {"name": "longmaytrai", "first_id": 0, "closed": false,
     "points": [{"id": 0, "x": 612.4, "y": 388.2, "state": "visible"}, ...]}
  ],
  "summary": {"visible": 44, "occluded": 4, "outside": 2},
  "warnings": []
}
```

`state` is derived from the guideline's rules and must be reviewed by a human:

| state | CVAT representation |
| --- | --- |
| `visible` | `outside = 0`, `occluded = 0` |
| `occluded` | `occluded = 1` |
| `outside` | `outside = 1` |

Hidden is never produced. `detected: false` means "no face in this frame" — the
guideline says to skip that frame.

## Run with Docker

```powershell
cd face50-server
docker compose up -d --build
curl http://localhost:58219/health
```

Host port 58219 maps to container port 8000 (`docker-compose.yml`). To use
another port, change the mapping there and set the same URL in the extension
options.

```powershell
docker compose logs -f face50     # startup + per-request errors
docker compose down               # stop
```

## Backends

| `FACE50_BACKEND` | model | needs | notes |
| --- | --- | --- | --- |
| `facemesh` (default) | MediaPipe FaceMesh (468 pts) | nothing, models ship in the pip package | offline, ~20 ms/frame |
| `tasks` | MediaPipe FaceLandmarker (478 pts) | `face_landmarker.task` at `FACE50_MODEL_PATH` | newer mesh, same derivation |
| `insight106` | InsightFace `2d106det` (106 pts) | the buffalo_l ONNX pack + the InsightFace wheels | stronger on profiles and older faces |

The 468-point backends derive the 50 points geometrically; `insight106` frames
already contain the eye / brow / mouth rings, so its 106 points are mapped
directly (`app/face50/mapping106.py`) and then run through the same ordering and
state code. The `source` of every shape stays the same for all backends.

### Trying InsightFace

```powershell
# 1. build an image that contains insightface + onnxruntime
docker compose build --build-arg FACE50_WITH_INSIGHTFACE=1

# 2. fetch the buffalo_l ONNX pack once (~280 MB, needs network)
Invoke-WebRequest `
  -Uri https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip `
  -OutFile models\buffalo_l.zip
Expand-Archive models\buffalo_l.zip -DestinationPath models\insightface\models\buffalo_l
```

(In a network-isolated deployment, run step 2 elsewhere and copy
`models/insightface/models/buffalo_l/` over. Only `det_10g.onnx` (17 MB) and
`2d106det.onnx` (5 MB) are loaded, so the other files in the pack can be
deleted. If the pack is missing and there is no network, the service logs a
clear error and falls back to `facemesh`.)

Then in `docker-compose.yml` uncomment the `volumes:` block and
`FACE50_BACKEND: "insight106"`, and `docker compose up -d`. `/health` reports
`"model": "insightface-2d106"`.

Note: the pack is downloaded automatically on first start if it is missing, so
step 2 is optional when the container has internet. If InsightFace fails to
start (missing pack, wheel mismatch), the service logs
`insightface backend unavailable (...)` and falls back to `facemesh` instead of
crashing.

### Checking a backend before using it

`tools/ab_backends.py` runs both backends on the same frame, prints the distance
between their 50-point sets, and writes `<name>_ab.png` with both overlaid:

```powershell
docker run --rm -v D:\frames:/data:ro -v "${PWD}\models:/app/models:ro" `
  cvat-face50:latest python tools/ab_backends.py /data/frame_0001.jpg
```

Expect a median of a few pixels on frontal frames. Measured on a frontal
portrait: median 1.6 px, max 10 px (nose bridge); eyebrows ~3 px, eyes and lips
~1–2 px.

Tens of pixels means the 106-index tables in `app/face50/mapping106.py` do not
match the model.

Keep `facemesh` for the bulk pass unless you measured a difference on your own
footage: the 50-point geometry is identical for both, and the states are
heuristics either way.

## Endpoints

| endpoint | purpose |
| --- | --- |
| `GET /health` | backend name, version, `strict` mode |
| `GET /topology` | group layout + the MediaPipe index sets used |
| `POST /predict` | 50 points with states (used by the extension) |
| `POST /render` | same analysis + a PNG overlay (base64) for visual checks |

### Verify the geometry before labelling 150 images

`/render` draws the derived 50 points on top of the frame, so a wrong MediaPipe
index set is visible immediately:

```powershell
$img = [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\frame_000123.jpg"))
$body = @{ image = $img; show_ids = $true } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri http://localhost:58219/render -Method Post `
  -ContentType 'application/json' -Body $body |
  Select-Object -ExpandProperty image |
  ForEach-Object { [IO.File]::WriteAllBytes("D:\tmp\face50_render.png", [Convert]::FromBase64String($_)) }
```

Check, on a few frames, that:

1. ids 0–9 follow the eyebrow ridges (image-left = `longmaytrai`, ids 0–4);
2. ids 10–13 run down the nose bridge, ending above the nostrils;
3. ids 14–29 are the eye contours, starting at the leftmost point, clockwise;
4. ids 30–41 are the outer lip ring and 42–49 the inner one, same rules;
5. colours are sensible: green `visible`, orange `occluded`, red `outside`.

If a group is wrong, adjust its index set in `app/face50/topology.py` (`MESH`)
and rebuild. Reordering inside a set is safe — the ordering of the 50 output
points comes from geometry (`app/face50/geometry.py`), not from the set order.

## Settings (environment)

| variable | default | meaning |
| --- | --- | --- |
| `FACE50_BACKEND` | `facemesh` | `facemesh` (bundled, offline), `tasks` or `insight106` |
| `FACE50_MODEL_PATH` | `/app/models/face_landmarker.task` | only for `tasks` |
| `FACE50_INSIGHTFACE_ROOT` | `/app/models/insightface` | only for `insight106`; expects `models/<pack>/*.onnx` |
| `FACE50_INSIGHTFACE_PACK` | `buffalo_l` | only for `insight106` |
| `FACE50_STRICT` | `1` | `1` = below the visible threshold the whole skeleton becomes Outside (guideline 3.1); `0` = Occluded |
| `FACE50_FAR_SIDE_START` | `0.45` | yaw ratio where the far-side eye/brow starts turning Occluded |
| `FACE50_FAR_SIDE_FULL` | `0.85` | yaw ratio where the far-side eye/brow becomes fully Occluded |
| `FACE50_BORDER_PX` | `0` | margin around the image treated as outside |
| `FACE50_MIN_DETECTION` | `0.4` | minimum face confidence |

## Labels (one-time setup per task)

The job must contain 7 skeleton labels with sublabels `p0` … `p49`. Two ways to
add them:

**A. Script (dry run first)**

```powershell
$env:CVAT_TOKEN = '<token from CVAT: profile -> Access tokens>'
python tools/setup_task.py --task-id 42              # prints the plan
python tools/setup_task.py --task-id 42 --apply      # PATCHes CVAT
```

`--job-id N` resolves the task; if the task belongs to a project, the script
targets the project, because that is where labels live. Only missing labels and
missing sublabels are sent (CVAT PATCH is an upsert), so existing labels,
attributes and annotations are untouched. It refuses to modify a same-named
label of a different type instead of overwriting it.

Caveat: if a skeleton already exists with *some* of its points, the script can
add the missing sublabels but cannot extend that label's SVG template (CVAT only
stores the template when the label is created). Creating them from this script
in one go avoids the problem; otherwise delete the incomplete label in the CVAT
UI and re-run.

**B. CVAT UI**

Open the task → *Labels* → *Raw* → paste the contents of `labels_raw.json` →
Save. Same JSON is available from the extension options page.

`labels_raw.json` is generated by `tools/labels_spec.py`; regenerate it (and the
extension copy) after changing `app/face50/topology.py`:

```powershell
python tools/labels_spec.py --out labels_raw.json
python tools/labels_spec.py --out ../face50-extension/labels_raw.json
```

## Local development (no Docker)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r tests\requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 58219
pytest -q
```

If `pip` has no MediaPipe wheel for your Python version, use Docker (it pins
Python 3.11).

## Known limitations

- MediaPipe outputs 468 points; the guideline's 50 are derived geometrically
  (corner/chord splits + width fractions). Expect ~1–3 px of disagreement with a
  human annotator; the tolerated error is ±5 px (visible) / ±20 px (occluded).
- The optional `insight106` backend maps a different topology (106 points) with
  the same geometric helpers. It is A/B-tested against `facemesh` on sample
  frames; if you use it, compare on your own frames before a full pass.
- Occlusion/outside is a heuristic: image bounds, a yaw proxy and the per-group
  visible thresholds. It cannot detect a hand or hair covering the face — those
  points must be fixed manually.
- Multiple faces: the largest face is annotated (the driver is assumed to be the
  most prominent). `face: "center"` is available for other shots.
- The model is a pre-label only. Every frame still has to be reviewed, per the
  guideline.

## Layout

```
app/main.py              HTTP surface (/health /topology /predict /render)
app/face50/topology.py   7 groups, thresholds, MediaPipe index sets
app/face50/geometry.py   468 -> 50 derivation (ordering, contour direction)
app/face50/mapping106.py InsightFace 106 -> 50 mapping (index sets, pose)
app/face50/states.py     visible/occluded/outside heuristics + group thresholds
app/face50/model.py      facemesh / tasks / insight106 backends, face selection
app/face50/pipeline.py   image decode -> response
app/face50/render.py     debug overlay used by /render
tools/labels_spec.py     labels_raw.json generator (single source of truth)
tools/setup_task.py      additive CVAT label setup
tools/ab_backends.py     facemesh vs insight106 distance check on a frame
tests/                   geometry, states, label spec, 106 mapping
```
