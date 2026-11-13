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
- **Point** mode: click an object → one shape. `Shift+click` = negative point.
- **Box** mode: drag a rectangle → one shape.
- Each result is written immediately. **Save** flushes any shapes you edited in
  CVAT itself (same as `Ctrl+S`), **Reload view** then shows everything on the
  same frame (`?frame=N` is preserved).
- **All** + a text prompt calls the model once for the whole frame. This needs a
  SAM 3 *concept* handler on the server (see below) — the current interactor
  returns nothing for text-only requests.

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
// response
{"shapes": [{"type": "mask", "points": [<rle...>, 0, 0, w-1, h-1]}]}
```

Note `obj_bbox` accepts either `[x1, y1, x2, y2]` or `[[x1, y1], [x2, y2]]`.

### Optional: real "automatic" segmentation

`sam3/main.py` is registered as `type: interactor` and its handler ignores
`prompt`. To make the **All** button work, add a concept branch next to the
existing one:

```python
from sam3.model.sam3_image_processor import Sam3Processor

# in ModelHandler.__init__
self.processor = Sam3Processor(self.model)

# in handler(), before the point/box path
prompt = data.get("prompt")
if prompt:
    state = self.processor.set_image(image)
    state = self.processor.set_text_prompt(state=state, prompt=prompt)
    masks = state["masks"]  # list of HxW boolean tensors
    return [mask_to_rle(m.astype("uint8")) for m in masks]
```

then return them as `shapes` in the same response envelope. That turns the
extension into text-prompted auto-annotation ("person, helmet, forklift").

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
