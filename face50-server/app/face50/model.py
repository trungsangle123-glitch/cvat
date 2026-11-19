"""Face landmark backends.

Three backends are supported:

* ``facemesh`` (default) - the legacy MediaPipe FaceMesh solution. It ships its
  .tflite models inside the pip package, so the container works fully offline.
* ``tasks`` - the newer MediaPipe FaceLandmarker task. Requires a
  ``face_landmarker.task`` model file (FACE50_MODEL_PATH).
* ``insight106`` - InsightFace ``2d106det`` from the buffalo_l pack. Stronger on
  profile / older faces, but needs the ONNX models mounted (and extra wheels).

The MediaPipe backends return 468 landmarks, the InsightFace one 106 landmarks.
Both are converted to the same 7 skeletons / 50 points; the derivation for 468
points happens in ``pipeline.py`` (``geometry.derive_50``), the 106-point
backend hands over ready-made groups (``mapping106.to_groups``).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .topology import CHEEK_LEFT, CHEEK_RIGHT, FACE_OVAL, NOSE_TIP


@dataclass
class DetectedFace:
    points: List[Tuple[float, float]]
    bbox: Tuple[float, float, float, float]
    score: float = 1.0
    # handedness / pose helpers
    yaw_ratio: float = 0.0
    yaw_deg: float = 0.0
    # set by backends that already know the 50 guideline points (e.g. insight106)
    groups: Optional[Dict[str, List[Tuple[float, float]]]] = None


def _bbox(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _pose(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Cheap yaw descriptor in [-1, 1] plus an approximate angle in degrees.

    Positive means the nose points to the right side of the image.
    """
    left = points[CHEEK_LEFT]
    right = points[CHEEK_RIGHT]
    nose = points[NOSE_TIP]
    width = abs(right[0] - left[0])
    if width < 1e-6:
        return 0.0, 0.0
    ratio = (nose[0] - (left[0] + right[0]) / 2.0) / width
    ratio = max(-1.0, min(1.0, ratio))
    # rough mapping: ratio 0.5 ~ 60 degrees, good enough for state heuristics
    deg = float(np.degrees(np.arcsin(max(-1.0, min(1.0, ratio * 2.0)))))
    return ratio, deg


def _face_from_landmarks(points: List[Tuple[float, float]], score: float = 1.0) -> DetectedFace:
    ratio, deg = _pose(points)
    oval = [points[i] for i in FACE_OVAL if i < len(points)]
    return DetectedFace(
        points=points,
        bbox=_bbox(oval or points),
        score=score,
        yaw_ratio=ratio,
        yaw_deg=deg,
    )


class FaceMeshBackend:
    name = "mediapipe-facemesh"

    def __init__(self, max_faces: int = 3, min_detection: float = 0.4) -> None:
        import mediapipe as mp

        self._mp = mp
        self._lock = threading.Lock()
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=max_faces,
            refine_landmarks=False,
            min_detection_confidence=min_detection,
        )
        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=min_detection,
        )

    def detect(self, rgb: np.ndarray) -> List[DetectedFace]:
        h, w = rgb.shape[:2]
        with self._lock:
            mesh_res = self._mesh.process(rgb)
            det_res = self._detector.process(rgb)

        scores = []
        for det in (det_res.detections or []):
            box = det.location_data.relative_bounding_box
            scores.append((
                (box.xmin * w, box.ymin * h, (box.xmin + box.width) * w, (box.ymin + box.height) * h),
                float(det.score[0]) if det.score else 1.0,
            ))

        faces: List[DetectedFace] = []
        for face_landmarks in (mesh_res.multi_face_landmarks or []):
            pts = [(p.x * w, p.y * h) for p in face_landmarks.landmark]
            box = _bbox(pts)
            score = _match_score(box, scores)
            faces.append(_face_from_landmarks(pts, score))
        return faces


class TasksBackend:
    name = "mediapipe-face-landmarker"

    def __init__(self, model_path: Optional[str] = None, max_faces: int = 3) -> None:
        import mediapipe as mp

        path = model_path or os.getenv("FACE50_MODEL_PATH", "")
        if not path or not os.path.exists(path):
            raise RuntimeError(
                "FACE50_BACKEND=tasks needs FACE50_MODEL_PATH pointing to face_landmarker.task"
            )
        self._lock = threading.Lock()
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=path),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=max_faces,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

    def detect(self, rgb: np.ndarray) -> List[DetectedFace]:
        import mediapipe as mp

        h, w = rgb.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        with self._lock:
            result = self._landmarker.detect(image)

        faces: List[DetectedFace] = []
        for landmarks in (result.face_landmarks or []):
            pts = [(p.x * w, p.y * h) for p in landmarks]
            faces.append(_face_from_landmarks(pts))
        return faces


class InsightFaceBackend:
    """InsightFace ``2d106det`` -> the 7 guideline skeletons.

    The ONNX pack (buffalo_l) is looked up under FACE50_INSIGHTFACE_ROOT, i.e.
    ``<root>/models/<pack>/det_10g.onnx`` and ``.../2d106det.onnx``; it is
    downloaded on first use when missing. Only the detector and the 106-point
    landmark model are loaded, so recognition and gender/age models cost no
    memory.
    """

    name = "insightface-2d106"

    def __init__(
        self,
        pack: Optional[str] = None,
        root: Optional[str] = None,
        det_size: int = 640,
        min_detection: float = 0.4,
    ) -> None:
        from insightface.app import FaceAnalysis

        pack = pack or os.getenv("FACE50_INSIGHTFACE_PACK", "buffalo_l")
        root = root or os.getenv("FACE50_INSIGHTFACE_ROOT", "/app/models/insightface")
        # FaceAnalysis.download() fetches <root>/models/<pack> from the insightface
        # GitHub release on first start (~280 MB, network needed once).
        self._app = FaceAnalysis(
            name=pack,
            root=root,
            allowed_modules=["detection", "landmark_2d_106"],
            providers=["CPUExecutionProvider"],
        )
        self._app.prepare(
            ctx_id=-1,
            det_thresh=min_detection,
            det_size=(det_size, det_size),
        )
        self._lock = threading.Lock()

    def detect(self, rgb: np.ndarray) -> List[DetectedFace]:
        from .mapping106 import ID_COUNT, bbox as contour_bbox, pose, to_groups

        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        with self._lock:
            raw = self._app.get(bgr)

        faces: List[DetectedFace] = []
        for found in raw:
            landmarks = getattr(found, "landmark_2d_106", None)
            if landmarks is None or len(landmarks) < ID_COUNT:
                continue
            pts = [(float(p[0]), float(p[1])) for p in landmarks]
            ratio, deg = pose(pts, rgb.shape[1], rgb.shape[0])
            det_box = getattr(found, "bbox", None)
            box = (
                (float(det_box[0]), float(det_box[1]), float(det_box[2]), float(det_box[3]))
                if det_box is not None and len(det_box) == 4
                else contour_bbox(pts)
            )
            faces.append(DetectedFace(
                points=pts,
                bbox=box,
                score=float(getattr(found, "det_score", 1.0)),
                yaw_ratio=ratio,
                yaw_deg=deg,
                groups=to_groups(pts),
            ))
        return faces


def _match_score(box, detections) -> float:
    if not detections:
        return 1.0
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    best = 1.0
    best_d = float("inf")
    for (dx1, dy1, dx2, dy2), score in detections:
        if dx1 <= cx <= dx2 and dy1 <= cy <= dy2:
            d = 0.0
        else:
            d = min(abs(cx - dx1), abs(cx - dx2)) + min(abs(cy - dy1), abs(cy - dy2))
        if d < best_d:
            best_d, best = d, score
    return best


def build_backend():
    """Create the configured backend, falling back to FaceMesh on failure."""
    choice = os.getenv("FACE50_BACKEND", "facemesh").strip().lower()
    min_conf = float(os.getenv("FACE50_MIN_DETECTION", "0.4"))
    if choice == "tasks":
        try:
            return TasksBackend(max_faces=3)
        except Exception as exc:  # pragma: no cover - depends on deployment
            print(f"[face50] tasks backend unavailable ({exc}); using facemesh")
    if choice in {"insight106", "insightface", "106"}:
        try:
            return InsightFaceBackend(min_detection=min_conf)
        except Exception as exc:  # pragma: no cover - depends on deployment
            print(f"[face50] insightface backend unavailable ({exc}); using facemesh")
    return FaceMeshBackend(min_detection=min_conf)


def pick_face(faces: List[DetectedFace], width: int, height: int, mode: str = "largest") -> Optional[DetectedFace]:
    if not faces:
        return None
    if len(faces) == 1:
        return faces[0]

    def area(f: DetectedFace) -> float:
        x1, y1, x2, y2 = f.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    if mode == "center":
        # driver: big and close to the lower centre of the cabin image
        def score(f: DetectedFace) -> float:
            x1, y1, x2, y2 = f.bbox
            cx, cy = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
            return area(f) * (1.0 - 0.5 * abs(cx - 0.5)) * (1.0 + 0.3 * cy)
        return max(faces, key=score)

    return max(faces, key=area)
