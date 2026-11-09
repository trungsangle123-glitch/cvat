# YOLO26 serverless function for CVAT

Runs [Ultralytics YOLO26](https://docs.ultralytics.com/models/yolo26) as a CVAT
serverless (Nuclio) detector.

- Default model: `yolo26n-objv1-150.pt` (Objects365, includes `car`, `truck`,
  `bus`, `van`), downloaded at image build time.
- Output labels: only `car`, `truck`, `bus`, `van`.
- Default device: CPU.
- Input: CVAT auto-annotation request (`image` as base64 + `threshold`).
- Output: rectangle shapes with `label`, `points`, `confidence`, `type`.

## Deploy

CVAT and Nuclio must be running with the serverless compose file:

```bash
docker compose -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml up -d
```

Use `nuctl` 1.16.x with the local platform. On Windows, run it from WSL
(the Windows `nuctl` binary cannot drive Docker for local deployments):

```bash
NUCTL=~/bin/nuctl-1.16.3 bash /mnt/d/Vinuni/cvat-day2/yolo26/deploy.sh
```

The first deployment builds a new Docker image (PyTorch CPU + Ultralytics +
YOLO26n weights) and can take several minutes. Check the state with:

```bash
nuctl get function ultralytics-yolo26 --platform local
```

Once ready, the model appears in CVAT as **YOLO26** in
**AI Tools → Detectors** (or **Auto-annotation**).

## Custom weights

1. Put your checkpoint in this folder (for example `best.pt`).
2. Update `spec.env` in `function.yaml`:
   `MODEL_PATH=/opt/nuclio/best.pt`.
3. Replace the label list in `metadata.annotations.spec` with your model's
   classes. The IDs and names must match the checkpoint.
4. Re-run `deploy.sh`. The model is copied into the image from this folder.

`TARGET_LABELS` in `function.yaml` controls which labels are returned. With the
default Objects365 checkpoint, `suv`/`sports car`/`race car` are folded into
`car`, and `pickup truck`/`fire truck` into `truck`; all other classes are
discarded.

## GPU

The function is configured for CPU. For a GPU deployment, change `DEVICE` to
`cuda:0`, install CUDA-enabled PyTorch in the build directives (or use the
`ultralytics/ultralytics` base image), and give the function access to the GPU
in its Nuclio platform configuration.

## Test the deployed function

```bash
nuctl get function ultralytics-yolo26 --platform local -o json
```

The output contains the function's node port. A direct request needs a
base64-encoded image:

```bash
curl -X POST http://127.0.0.1:<node-port> \
  -H 'Content-Type: application/json' \
  -d '{"image": "<base64>", "threshold": 0.25}'
```
