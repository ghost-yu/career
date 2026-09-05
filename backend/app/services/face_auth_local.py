from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import settings
from app.utils.ids import now_iso

_DATA_URL_RE = re.compile(r"^data:image/[^;]+;base64,", re.IGNORECASE)


def _face_dir() -> Path:
    base = Path(os.getenv("FACE_AUTH_DATA_DIR") or Path(settings.data_dir) / "face_auth")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_user_id(user_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(user_id or "").strip())
    return safe[:96] or "anonymous"


def _decode_image(image: str) -> np.ndarray:
    raw = _DATA_URL_RE.sub("", str(image or "").strip())
    if not raw:
        raise ValueError("empty_image")
    data = base64.b64decode(raw, validate=False)
    import cv2

    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise ValueError("invalid_image")
    return frame


def _cascade_path() -> str:
    import cv2

    return str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")


def _extract_face(frame: np.ndarray) -> np.ndarray:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    detector = cv2.CascadeClassifier(_cascade_path())
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
    if len(faces) == 0:
        raise ValueError("no_face_detected")
    x, y, w, h = max(faces, key=lambda item: int(item[2]) * int(item[3]))
    pad = int(max(w, h) * 0.12)
    y0 = max(0, y - pad)
    y1 = min(gray.shape[0], y + h + pad)
    x0 = max(0, x - pad)
    x1 = min(gray.shape[1], x + w + pad)
    face = gray[y0:y1, x0:x1]
    if face.size == 0:
        raise ValueError("empty_face")
    face = cv2.resize(face, (160, 160), interpolation=cv2.INTER_AREA)
    return face


def _face_embedding(face: np.ndarray) -> np.ndarray:
    import cv2

    hist = cv2.calcHist([face], [0], None, [64], [0, 256]).astype("float32").flatten()
    hist = hist / max(float(hist.sum()), 1e-6)
    gx = cv2.Sobel(face, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(face, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    edge_hist = cv2.calcHist([np.uint8(np.clip(mag, 0, 255))], [0], None, [32], [0, 256]).astype("float32").flatten()
    edge_hist = edge_hist / max(float(edge_hist.sum()), 1e-6)
    thumb = cv2.resize(face, (32, 32), interpolation=cv2.INTER_AREA).astype("float32").flatten() / 255.0
    vector = np.concatenate([hist, edge_hist, thumb])
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-6:
        raise ValueError("invalid_face_vector")
    return vector / norm


def _template_path(user_id: str) -> Path:
    return _face_dir() / f"{_safe_user_id(user_id)}.json"


def _image_path(user_id: str) -> Path:
    return _face_dir() / f"{_safe_user_id(user_id)}.jpg"


def _result(status: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "message": message, "msg": message, **extra}


def register_face_local(image: str, user_id: str) -> dict[str, Any]:
    uid = _safe_user_id(user_id)
    if not image or not uid:
        return _result("1", "请先开启摄像头并登录账号")
    try:
        frame = _decode_image(image)
        face = _extract_face(frame)
        embedding = _face_embedding(face)
    except ValueError as exc:
        reason = str(exc)
        if reason == "no_face_detected":
            return _result("1", "未检测到清晰人脸，请正对摄像头重新拍照")
        return _result("1", "人脸注册未完成，请重新拍照")

    import cv2

    cv2.imwrite(str(_image_path(uid)), face)
    payload = {
        "user_id": uid,
        "created_at": now_iso(),
        "method": "opencv_histogram_v1",
        "embedding": embedding.astype(float).tolist(),
    }
    _template_path(uid).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return _result("0", "人脸注册完成", method="opencv_local", userId=uid)


def verify_face_local(image: str, user_id: str) -> dict[str, Any]:
    uid = _safe_user_id(user_id)
    path = _template_path(uid)
    if not path.exists():
        return _result("1", "请先完成人脸注册")
    try:
        template = json.loads(path.read_text(encoding="utf-8"))
        saved = np.asarray(template.get("embedding") or [], dtype="float32")
        frame = _decode_image(image)
        face = _extract_face(frame)
        current = _face_embedding(face)
    except ValueError as exc:
        reason = str(exc)
        if reason == "no_face_detected":
            return _result("1", "未检测到清晰人脸，请正对摄像头重新拍照")
        return _result("1", "身份认证未通过，请重新拍照")
    except Exception:
        return _result("1", "身份认证未通过，请重新拍照")

    if saved.size != current.size:
        return _result("1", "身份认证未通过，请重新注册")
    similarity = float(np.dot(saved, current) / max(float(np.linalg.norm(saved) * np.linalg.norm(current)), 1e-6))
    threshold = float(os.getenv("FACE_AUTH_THRESHOLD") or 0.86)
    passed = similarity >= threshold
    return _result(
        "0" if passed else "1",
        "人脸认证通过" if passed else "身份认证未通过，请重新拍照",
        similarity=round(similarity, 4),
        threshold=threshold,
        method="opencv_local",
        userId=uid,
    )
