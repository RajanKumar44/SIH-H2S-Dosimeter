"""
ml_inference.py
===============
Thin bridge from the backend to the standalone ML pipeline in
``software/ml_pipeline``.

Why this module exists
----------------------
The backend deliberately does **not** depend on OpenCV or scikit-learn: see the
architecture rule in ``CLAUDE.md`` — the backend stores/aggregates/alerts and
receives an already-computed ``dose_ppm_hr`` from the client.

``POST /readings/scan`` is a pragmatic exception. It lets the dashboard (and any
phone browser) submit a photo without shipping a JavaScript reimplementation of
CIE ΔE2000 and a RandomForest. To keep that exception contained:

* every heavy import happens **lazily inside** :func:`analyze_strip_image`, so
  importing this module — or the rest of the backend, or running
  ``test_offline_checks.py`` — never requires OpenCV or scikit-learn;
* the ML code itself is reused unchanged. Nothing here reimplements colour
  science, feature engineering or the dose model;
* a missing dependency or missing model file surfaces as
  :class:`MLUnavailable`, which the route maps to a clean 503 rather than a
  stack trace.

The trained model is regenerated locally (``models/`` is git-ignored):

    cd software/ml_pipeline && python demo_simulator.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# software/backend/ml_inference.py -> software/ml_pipeline
_ML_DIR = (Path(__file__).resolve().parent.parent / "ml_pipeline")
_MODEL_PATH = _ML_DIR / "models" / "h2s_model.pkl"

# Upload guard rails. Kept here rather than in the route so the limits are
# testable without spinning up FastAPI.
MAX_IMAGE_BYTES = 12 * 1024 * 1024          # 12 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/jpg", "image/png",
    "image/pjpeg",                           # some Android browsers
    "application/octet-stream",               # some clients omit a real type
}
# Longest edge the strip analysis needs. Phone cameras produce 4000px+ frames;
# downscaling first keeps latency low and does not affect the mean/median
# colour of a large uniform patch.
MAX_ANALYSIS_EDGE = 1600


class MLUnavailable(RuntimeError):
    """The ML pipeline cannot run (missing dependency or missing model file)."""


class InvalidImage(ValueError):
    """The uploaded bytes are not a decodable JPEG/PNG image."""


def _ensure_ml_path() -> None:
    """Put the ml_pipeline directory on sys.path (its modules use flat imports)."""
    p = str(_ML_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def model_status() -> dict:
    """
    Report whether a scan can currently be served, without importing anything
    heavy beyond a dependency probe. Used by the route to answer 503 early and
    by tests to skip cleanly.
    """
    status = {
        "model_path": str(_MODEL_PATH),
        "model_present": _MODEL_PATH.is_file(),
        "dependencies_present": True,
        "missing": [],
    }
    for mod in ("cv2", "numpy", "joblib", "sklearn", "pandas"):
        try:
            __import__(mod)
        except Exception:                                   # noqa: BLE001
            status["dependencies_present"] = False
            status["missing"].append(mod)

    status["available"] = status["model_present"] and status["dependencies_present"]
    if not status["model_present"]:
        status["hint"] = (
            "Trained model not found. Generate it with: "
            "cd software/ml_pipeline && python demo_simulator.py"
        )
    elif not status["dependencies_present"]:
        status["hint"] = (
            "Missing ML dependencies: " + ", ".join(status["missing"])
            + ". Install with: pip install -r software/ml_pipeline/requirements.txt"
        )
    return status


def analyze_strip_image(
    image_bytes: bytes,
    measured_patches: Optional[dict] = None,
) -> dict:
    """
    Run the full colour + ML pipeline on raw uploaded image bytes.

    Reuses ``image_processor.process_strip_array`` and
    ``model_trainer.predict`` exactly as the standalone pipeline does — this
    function only decodes, downscales and marshals results.

    Args:
        image_bytes: Raw JPEG/PNG bytes.
        measured_patches: Optional reference-card Lab measurements. There is no
            automatic card detector in this repository, so in practice this is
            None and no lighting correction is applied — the returned
            ``lighting_corrected`` flag says so honestly.

    Returns:
        A flat dict of colour metrics, ROI diagnostics and the model's dose
        prediction. ``dose_ppm_hr`` is what the caller stores.

    Raises:
        InvalidImage: bytes are empty, oversized or not a decodable image.
        MLUnavailable: dependencies or the trained model are missing, or
            inference failed.
    """
    if not image_bytes:
        raise InvalidImage("Empty image payload.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise InvalidImage(
            f"Image is too large ({len(image_bytes) / 1e6:.1f} MB). "
            f"Limit is {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )

    _ensure_ml_path()

    # ── Lazy imports: keep OpenCV/sklearn out of the backend's import graph ──
    try:
        import cv2
        import numpy as np
    except Exception as e:                                  # noqa: BLE001
        raise MLUnavailable(
            f"Image processing dependencies unavailable ({e}). "
            f"Install: pip install -r software/ml_pipeline/requirements.txt"
        ) from e

    # ── Decode ──────────────────────────────────────────────────────────────
    try:
        buf = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception as e:                                  # noqa: BLE001
        raise InvalidImage(f"Could not decode image bytes: {e}") from e

    if img is None or img.size == 0:
        raise InvalidImage(
            "Could not decode the image. Supported formats are JPEG and PNG."
        )
    if img.ndim != 3 or img.shape[2] != 3:
        raise InvalidImage("Expected a 3-channel colour image.")
    if min(img.shape[:2]) < 16:
        raise InvalidImage(
            f"Image is too small to analyse ({img.shape[1]}x{img.shape[0]} px)."
        )

    # Downscale very large phone frames — cheaper and colour-neutral.
    longest = max(img.shape[:2])
    if longest > MAX_ANALYSIS_EDGE:
        scale = MAX_ANALYSIS_EDGE / float(longest)
        img = cv2.resize(
            img,
            (max(1, int(img.shape[1] * scale)), max(1, int(img.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )

    # ── Colour pipeline + model (both reused unchanged) ─────────────────────
    if not _MODEL_PATH.is_file():
        raise MLUnavailable(
            f"Trained model not found at {_MODEL_PATH}. Generate it with: "
            f"cd software/ml_pipeline && python demo_simulator.py"
        )

    try:
        from image_processor import process_strip_array
        from model_trainer import predict
    except Exception as e:                                  # noqa: BLE001
        raise MLUnavailable(f"Could not import the ML pipeline ({e}).") from e

    try:
        reading = process_strip_array(img, measured_patches=measured_patches)
    except Exception as e:                                  # noqa: BLE001
        log.exception("Strip image processing failed")
        raise MLUnavailable(f"Image processing failed: {e}") from e

    try:
        prediction = predict(reading.features_for_model(), model_path=str(_MODEL_PATH))
    except Exception as e:                                  # noqa: BLE001
        log.exception("Dose prediction failed")
        raise MLUnavailable(f"Dose prediction failed: {e}") from e

    return {
        # Colour science
        "delta_E": round(float(reading.delta_E), 4),
        "delta_E_corr": round(float(reading.delta_E_corr), 4),
        "R": round(float(reading.R), 2),
        "G": round(float(reading.G), 2),
        "B": round(float(reading.B), 2),
        "L_star": round(float(reading.L), 3),
        "a_star": round(float(reading.a), 3),
        "b_star": round(float(reading.b), 3),
        "H": round(float(reading.H), 3),
        "S": round(float(reading.S), 4),
        "V": round(float(reading.V), 4),
        # Model output
        "dose_ppm_hr": round(float(prediction["dose_ppm_hr"]), 3),
        "model_confidence": prediction["confidence"],
        "model_name": prediction.get("model"),
        # Diagnostics — let the UI show when a reading should not be trusted
        "image_confidence": round(float(reading.confidence), 4),
        "roi_detected": bool(reading.roi_detected),
        "roi_method": reading.roi_method,
        "roi_confidence": round(float(reading.roi_confidence), 4),
        "roi_reason": reading.roi_reason,
        "lighting_corrected": bool(reading.lighting_corrected),
        "correction_method": reading.correction_method,
    }
