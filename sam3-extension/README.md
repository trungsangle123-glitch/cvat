# CVAT SAM 3 Segment (browser extension)

Click-to-segment inside **any** CVAT instance (including hosted ones where you
cannot register serverless functions), using a SAM 3 model you host yourself.

Works in Chrome, Edge, Brave and any Chromium browser (MV3).

## How it works

The extension never touches CVAT's React state or `cvat-core`. It uses only
public surfaces:

| Step | What |
| --- | --- |
| 1 | Read the current frame pixels from `#cvat_canvas_background`. `cvat-data` sizes that canvas from the frame metadata, so it is the source resolution — 1 canvas px = 1 image px. |
| 2 | Map the click / drag to image coordinates. |
| 3 | `POST` `{"image": <base64>, "pos_points": ..., "neg_points": ..., "obj_bbox": ...}` to your SAM 3 function (via the service worker, so CORS does not apply). |
| 4 | Convert the mask RLE to the selected shape type, then `PATCH /api/jobs/<id>/annotations/?action=create` using the page session cookie + `X-CSRFToken`. |
| 5 | Preview the new shape on an overlay. The annotator shows saved shapes after a reload. |

No server-side changes, no admin rights on `cvat.edufun.ai`, no API token.

## Install

1. `chrome://extensions` (or `edge://extensions`, `brave://extensions`)
2. Enable **Developer mode**
3. **Load unpacked** → select this folder
4. Open the extension options and check the SAM 3 URL
   (default `http://localhost:58218/` — the port published by your
   `nuclio-nuclio-pth-facebookresearch-sam3` container). **Test connection**.
5. Open a job: `https://cvat.edufun.ai/tasks/<id>/jobs/<id>`

## Use

- `Alt+S` toggles SAM mode (or the switch in the panel).
- Drag the panel by its header to move it; the position is remembered.
- **Shape: Polygon** (default) writes filled polygons; **Mask** writes CVAT
  masks (brush). The label list only shows labels CVAT will accept for the
  selected shape type, so polygon mode lists `polygon`/`any` labels and mask
  mode lists `mask`/`any`.
- **Grid** draws a non-interactive grid over the image (edge length in image
  pixels, default 32) to help painting with CVAT's brush. It sits on a separate
  overlay, so it never blocks clicks or brush strokes.
- **Point** mode: click an object → one shape. `Shift+click` = negative point.
- **Box** mode: drag a rectangle → one shape.
- Each result is written immediately. **Save** flushes any shapes you edited in
  CVAT itself (same as `Ctrl+S`), **Reload view** then shows everything on the
  same frame (`?frame=N` is preserved).
- **All** + a text prompt asks the model for every object matching the concept
  in the current frame and adds them all at once (best score first). The server
  needs the text-prompt branch that `../sam3/main.py` now has. On CPU the first
  call for a frame takes ~25 s (image embedding); later prompts on the same
  frame reuse that embedding and finish in seconds.
- **All frames** runs that same prompt over the whole job: it jumps to the first
  frame, segments, writes the shapes, then clicks CVAT's own *next frame*
  button (so deleted / step / included frames behave exactly like manual work)
  and repeats until the last frame. A confirmation shows the frame count first
  — on CPU budget ~25 s for the first frame and a few seconds for the rest.
  The button turns into **Stop**; it stops after the current frame (already
  written shapes stay). Progress is shown next to the button. If the *next*
  button was switched to filtered/empty/chapter navigation (right-click menu),
  switch it back to regular frames. Requires a text prompt.

## Requirements on the CVAT side

- A label the selected shape type accepts in the task (otherwise the API rejects
  the shape, and the panel tells you):
  - polygon mode → label type `polygon` or `any`;
  - mask mode → label type `mask` or `any`.
- 2D jobs (images or video). Point clouds are not supported.

## Requirements on the model side

The function must speak the CVAT interactor contract, which
`../sam3/main.py` already does:

```json
// request
{"image": "<base64 jpeg>", "pos_points": [[x, y]], "neg_points": [], "obj_bbox": null}
// text prompt request
{"image": "<base64 jpeg>", "prompt": "car", "confidence": 0.5}
// response
{"shapes": [{"type": "mask", "points": [<rle...>, 0, 0, w-1, h-1]}]}
```

Note `obj_bbox` accepts either `[x1, y1, x2, y2]` or `[[x1, y1], [x2, y2]]`.
When `prompt` is set, the handler runs SAM 3's concept grounding and returns one
mask per match; `confidence` is optional (default 0.5).

## Files

```
manifest.json    MV3 manifest (content script is limited to cvat.edufun.ai by default)
background.js    SAM 3 proxy (bypasses CORS via host_permissions)
content.js       panel, coordinate mapping, RLE preview, CVAT API writes
options.html/js  endpoint, timeout, extra CVAT sites
icons/           toolbar icons
```

## Limitations

- CVAT polygons cannot hold holes, so polygon mode fills interior holes before
  tracing. Use **Mask** shape if holes matter.
- Mask previews live on an overlay until the annotator reloads; they are not
  interactive (you cannot edit them before saving).
- Each click sends a JPEG of the current frame to the model. On a 4K frame with
  CPU inference this is slow — expect 10–60 s per object depending on hardware.
- `action=create` appends; it never edits or deletes existing shapes.
- **All frames** keeps going on empty frames but aborts after three hard errors
  in a row (model down, timeout, rejected write). Frames processed before a
  stop are already saved on the server.
