# CVAT + SAM 3 — Runbook

Quick reference for running CVAT with **SAM 3** (local Nuclio + Colab GPU).

---

## Everyday startup

### 1. Start Docker Desktop (if not running)

```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
# wait ~1 minute, then verify:
docker ps --format "{{.Names}} {{.Status}}" | findstr "cvat nuclio gateway"
```

You need `cvat_server`, `nuclio`, `sam3_colab_gateway` all **Up**.

- **CVAT UI:** http://localhost:8080
- **Nuclio dashboard:** http://localhost:8070

### 2. Use SAM 3 in CVAT

Open a job → **AI Tools → Interactors**:

| Function | Runs on | Speed |
|---|---|---|
| **Segment Anything 3 (Colab GPU)** | Google Colab | ~1–3 s per click |
| **Segment Anything 3** | Local CPU | ~20 s per click |
| Segment Anything (vit-h), YOLO26 | Local | — |

> ⚠️ The local CPU function needs ~7 GB RAM and can get OOM-killed (exit 137) or
> die right after a deploy (exit 2) under memory pressure. If it dies again
> (500 from local function):
>
> ```powershell
> docker start nuclio-nuclio-pth-facebookresearch-sam3
> ```
>
> Wait ~2 min for model load, then retry. If `docker start` doesn't fix it,
> redeploy: `wsl bash -lc "cd /mnt/d/Vinuni/cvat-day2 && NUCTL=nuctl bash sam3/deploy.sh"`

---

## Colab session startup (new Colab session)

The tunnel URL **changes every new Colab session**, so redo these each time:

1. Open `sam3/colab/sam3_colab_server.ipynb` in Google Colab
2. **Runtime → Change runtime type → T4 GPU**
3. **Run all cells** (checkpoint download ~3.45 GB takes a few minutes on first cell)
4. The last cell prints the tunnel URL:
   `COLAB_FUNCTION_URL = https://random-words.trycloudflare.com`
5. On your PC (repo root):

   ```powershell
   powershell -File sam3\colab\update-colab-url.ps1 -Url https://random-words.trycloudflare.com
   ```

   No CVAT server restart needed.
6. In CVAT use **AI Tools → Interactors → Segment Anything 3 (Colab GPU)**.
   **Keep the Colab tab open** while annotating.

### When done annotating

Colab → **Runtime → Disconnect and delete runtime** (frees GPU quota).

> First click on a fresh Colab session is slower (~30–60 s) — the model does
> GPU warm-up.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Colab function missing from the list | Colab not running / URL stale | Re-run the notebook, redo the `update-colab-url.ps1` step |
| `405` / `502` errors in CVAT dialog | Wrong or dead tunnel URL | Copy the **boxed** URL from the tunnel cell (not `https://api.trycloudflare.com`!), run `update-colab-url.ps1` |
| `SAM3 Colab server error: ...` in the CVAT dialog | Crash inside the Colab server | Full traceback prints in the Colab cell output — re-run cells 3 + 4 (server definition + start server); do **not** re-run the tunnel cell if the tunnel is still alive |
| **Local** "Segment Anything 3" returns 500 | Function container died (exit 2 / 137) | `docker start nuclio-nuclio-pth-facebookresearch-sam3`, wait ~2 min; if that fails, redeploy: <br>`wsl bash -lc "cd /mnt/d/Vinuni/cvat-day2 && NUCTL=nuctl bash sam3/deploy.sh"` |
| CVAT UI unreachable (connection closed) | Stale Docker port-forwarding | `docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml up -d --force-recreate traefik` and `docker restart nuclio` |
| Docker Desktop unresponsive / crash during model tests | WSL memory saturation | Restart Docker Desktop + `wsl --shutdown` (`.wslconfig` is set to 16 GB) |

---

## Architecture

```
CVAT server ──> sam3_colab_gateway (container) ──> http://nuclio:8070  (local functions)
                                            └──> https://<tunnel>     (SAM 3 in Colab)
```

- `sam3/colab/sam3_colab_server.ipynb` — SAM 3 server on Colab (T4 GPU)
- `sam3/colab/gateway/` — multiplexing gateway container
- `docker-compose.sam3-colab.yml` — adds the gateway + points CVAT at it
- `sam3/colab/.env` — holds `COLAB_FUNCTION_URL`
- `sam3/` — local CPU Nuclio function (SAM 3) + `deploy.sh`

### Fully local mode (no Colab)

Restart the stack without the Colab override:

```bash
docker compose -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml up -d
```

### Full stack restart (with Colab gateway)

```bash
docker compose -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml \
  -f docker-compose.sam3-colab.yml \
  --env-file sam3/colab/.env up -d
```
