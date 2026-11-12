# SAM 3 on Google Colab for CVAT

Runs **Segment Anything 3** on a free Colab GPU and connects it to the local CVAT
through a Cloudflare tunnel. The local Nuclio functions keep working - a small
gateway container merges them with the Colab one.

## Architecture

```
cvat_server --> sam3_colab_gateway (container) --> http://nuclio:8070  (local functions)
                                             \--> https://<tunnel>    (SAM 3 in Colab)
```

## How to run

1. Open `sam3/colab/sam3_colab_server.ipynb` in Google Colab and select the
   **T4 GPU** runtime. Run all cells. The last cell prints a
   `COLAB_FUNCTION_URL = https://xxx.trycloudflare.com`.

2. On your PC, from the repo root:

   ```powershell
   powershell -File sam3\colab\update-colab-url.ps1 -Url https://xxx.trycloudflare.com
   docker restart cvat_server
   ```

3. Open a job in CVAT. **AI Tools > Interactors** now shows both
   **Segment Anything 3** (local, CPU) and **Segment Anything 3 (Colab GPU)**.

## Notes

- Colab URLs change every new Colab session. When Colab restarts, re-run the
  tunnel cell and `update-colab-url.ps1` (no need to restart cvat_server unless
  the gateway is recreated).
- Keep the Colab tab open while annotating - Colab disconnects idle tabs.
- Pointing CVAT at the gateway does not change the local functions; if the
  Colab tunnel is down, only the Colab function disappears from the list.
- To go back to plain local serverless, restart the stack without the Colab
  override file:

  ```bash
  docker compose -f docker-compose.yml \
    -f components/serverless/docker-compose.serverless.yml up -d
  ```
