# SAM 3 serverless function for CVAT

Runs [Segment Anything Model 3](https://github.com/facebookresearch/sam3) as a
CVAT serverless (Nuclio) interactor.

- Function name in CVAT: **Segment Anything 3**
- Prompt types: positive points, negative points, bounding box
- Output: one mask shape (CVAT compressed RLE)
- Default device: CPU (change `DEVICE` in `function.yaml` to `cuda:0` for GPU)
- Checkpoint: `sam3.pt` downloaded at image build time

## Deploy

CVAT and Nuclio must be running with the serverless compose file:

```bash
docker compose -f docker-compose.yml \
  -f components/serverless/docker-compose.serverless.yml up -d
```

On Windows, run `nuctl` from WSL:

```bash
cd /mnt/c/Users/Sang/Documents/GitHub/cvat
NUCTL=~/bin/nuctl-1.16.3 bash sam3/deploy.sh
```

The first deployment builds the image (PyTorch CPU + SAM 3 + 3.45 GB
checkpoint) and takes a while. Check the state with:

```bash
nuctl get function pth-facebookresearch-sam3 --platform local
```

Once ready, open a job in CVAT and select **Segment Anything 3** in
**AI Tools → Interactors**.

## Notes

- CPU inference is slow (tens of seconds per image embedding). A CUDA GPU is
  strongly recommended for production use.
- The container needs at least ~12 GB of RAM to load the 3.45 GB checkpoint
  next to the rest of the CVAT stack. On Windows, Docker Desktop takes its
  memory limit from `%USERPROFILE%\.wslconfig` (`[wsl2] memory=12GB`).
- SAM 3 precomputes position-encoding caches on `cuda` unconditionally; the
  build patches that in `position_encoding.py` and `decoder.py` so the model
  can be constructed on CPU-only hosts.
- The image is built from the ungated `1038lab/sam3` mirror of the official
  `facebook/sam3` checkpoint. To use the official gated repository, edit the
  checkpoint download step in `function.yaml` and pass a Hugging Face token.
- To rebuild after changing `main.py` or `function.yaml`, re-run `deploy.sh`.
