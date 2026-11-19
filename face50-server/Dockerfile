FROM python:3.11-slim

# Set to 1 to also install InsightFace (FACE50_BACKEND=insight106). That pulls a
# compiler for the insightface cython extension and ~400 MB of wheels, so it is
# opt-in: docker compose build --build-arg FACE50_WITH_INSIGHTFACE=1
ARG FACE50_WITH_INSIGHTFACE=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FACE50_BACKEND=facemesh \
    FACE50_INSIGHTFACE_ROOT=/app/models/insightface

# opencv (pulled in by mediapipe) needs these at import time
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY requirements-insightface.txt .
RUN if [ "$FACE50_WITH_INSIGHTFACE" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends build-essential \
        && pip install -r requirements-insightface.txt \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Optional model files (only needed by the tasks / insight106 backends):
#   /app/models/face_landmarker.task              FACE50_BACKEND=tasks
#   /app/models/insightface/models/buffalo_l/*    FACE50_BACKEND=insight106
# Mount them instead of baking them in, e.g.
#   -v ./models/insightface:/app/models/insightface:ro
RUN mkdir -p /app/models
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
