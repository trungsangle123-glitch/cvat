# YOLO26 for CVAT — Step-by-Step Setup

This guide configures and deploys the YOLO26 serverless detector for CVAT.

- Labels: `car`, `truck`, `van`, `bus`, `motorcycle`, `tuk_tuk`, `bicycle`,
  `cyclo`, `person`, `ignore_region` (each with `occluded_level`, `truncated`,
  `can_review` attributes, except `ignore_region`)
- Model: `yolo26n-objv1-150.pt` (Ultralytics YOLO26, Objects365-pretrained)
- Device: CPU
- Function name in CVAT: **YOLO26**

---

## 1. Start CVAT + Nuclio

From `D:\Vinuni\cvat-day2`:

```powershell
docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml up -d
```

Check that both are running:

```powershell
docker ps --format "{{.Names}}`t{{.Status}}" | Select-String "cvat_server|nuclio"
```

---

## 2. Check the function files

They are in `D:\Vinuni\cvat-day2\yolo26\`:

- `function.yaml` — model, labels, build config
- `main.py` — inference handler
- `deploy.sh` — deployment script
- `README.md` — notes

Key config already set:

```yaml
spec:
  env:
    - name: MODEL_PATH
      value: /opt/nuclio/yolo26n-objv1-150.pt   # Objects365 model
    - name: DEVICE
      value: cpu
    - name: TARGET_LABELS
      value: car,truck,bus,van,motorcycle,bicycle,person,cyclo,tuk_tuk

metadata:
  annotations:
    name: YOLO26
    type: detector
    spec: |
      [
        { "name": "car", "type": "rectangle", "attributes": [...] },
        { "name": "truck", "type": "rectangle", "attributes": [...] },
        { "name": "van", "type": "rectangle", "attributes": [...] },
        { "name": "bus", "type": "rectangle", "attributes": [...] },
        { "name": "motorcycle", "type": "rectangle", "attributes": [...] },
        { "name": "tuk_tuk", "type": "rectangle", "attributes": [...] },
        { "name": "bicycle", "type": "rectangle", "attributes": [...] },
        { "name": "cyclo", "type": "rectangle", "attributes": [...] },
        { "name": "person", "type": "rectangle", "attributes": [...] },
        { "name": "ignore_region", "type": "rectangle", "attributes": [] }
      ]
```

---

## 3. Deploy

Open WSL:

```powershell
wsl -d Ubuntu
```

Then:

```bash
sanglt5@DESKTOP-C9F73BV:/mnt/d/Vinuni/cvat-day2$ NUCTL=~/bin/nuctl-1.16.3 bash yolo26/deploy.sh
cd /mnt/d/Vinuni/cvat-day2
NUCTL=~/bin/nuctl-1.16.3 bash yolo26/deploy.sh
```

The first build takes a few minutes. It installs CPU PyTorch, Ultralytics, and downloads the YOLO26 Objects365 weights.

---

## 4. Verify deployment

```bash
nuctl get function ultralytics-yolo26 --platform local
```

Expected:

```text
NAME                 PROJECT   STATE   REPLICAS   NODE PORT
ultralytics-yolo26   cvat      ready   1/1        53158
```

---

## 5. Use in CVAT

1. Refresh the CVAT page.
2. Open a task or job.
3. Go to **AI Tools → Detectors** or **Auto-annotation**.
4. Select **YOLO26**.
5. Set **Threshold**:
   - `0.25` → more detections, best if you will review
   - `0.50` → cleaner, fewer false positives
6. Map the labels: `car`, `truck`, `van`, `bus`, `motorcycle`, `tuk_tuk`,
   `bicycle`, `cyclo`, `person`, `ignore_region` (`tuk_tuk` and
   `ignore_region` are never auto-detected by the default checkpoint).
7. Run it.

Threshold is a **run setting in CVAT**, not a per-image count setting. It does not change based on 50 vs 500 images.

---

## 6. If you change the config later

Edit `function.yaml` or `main.py`, then rebuild:

```bash
cd /mnt/d/Vinuni/cvat-day2
NUCTL=~/bin/nuctl-1.16.3 bash yolo26/deploy.sh
```

---

## 7. Use your own 4-class model (optional)

1. Put `best.pt` inside `yolo26/`.
2. In `function.yaml`, change:

```yaml
MODEL_PATH=/opt/nuclio/best.pt
```

3. Keep the 4-label spec matching your model's class IDs.
4. Redeploy with the command from step 6.

---

## 8. Common checks

```bash
nuctl get function ultralytics-yolo26 --platform local
docker logs --tail 50 nuclio-nuclio-ultralytics-yolo26
```

If the model is not visible in CVAT, refresh the page and confirm the function state is `ready`.
