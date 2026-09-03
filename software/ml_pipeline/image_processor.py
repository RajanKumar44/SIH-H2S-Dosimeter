"""
image_processor.py
==================
Core image processing module for the H2S colorimetric dosimeter system.

Pipeline:
  Camera photo --> ROI detection --> Color extraction --> RGB->Lab conversion
  --> CIE DE2000 deltaE calculation --> Reference card normalization --> Output

Based on formulas from:
  "Deep learning-assisted colorimetric/electrical dual-sensing system for
   ultra-fast detection of hydrogen sulfide" (ACS, se3c02793)
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data container for a single strip reading
# ---------------------------------------------------------------------------
@dataclass
class StripReading:
    """All color metrics extracted from one strip photo."""
    # Raw mean RGB of the strip ROI (0-255)
    R: float
    G: float
    B: float
    # CIE L*a*b* values
    L: float
    a: float
    b: float
    # CIE DE2000 color difference from fresh (unexposed) baseline
    delta_E: float
    # HSV in the CANONICAL convention (see rgb_to_hsv): H in degrees [0,360),
    # S and V in [0,1]. Derived from the mean RGB above, never averaged
    # channel-wise out of an HSV image.
    H: float
    S: float
    V: float
    # Lighting-corrected Lab values (after reference card normalization).
    # When no correction is applied these equal L/a/b and delta_E_corr equals
    # delta_E — check `lighting_corrected` to tell the two cases apart.
    L_corr: float
    a_corr: float
    b_corr: float
    delta_E_corr: float
    # ROI reliability (0-1). Reflects how well the strip region was located:
    # a scored geometric/chromatic match, NOT merely "the code returned a
    # number". A center-crop fallback scores low on purpose.
    confidence: float = 1.0
    # ── ROI diagnostics ─────────────────────────────────────
    roi_detected: bool = True
    roi_method: str = "contour_score"
    roi_confidence: float = 1.0
    roi_bbox: Optional[Tuple[int, int, int, int]] = None
    roi_reason: str = ""
    # ── Lighting-correction diagnostics ─────────────────────
    # False means the raw measurement was used unchanged. There is no
    # reference-card *detector* in this repository, so this is only True when
    # a caller supplies measured patches explicitly.
    lighting_corrected: bool = False
    correction_method: str = "none"

    def features_for_model(self) -> dict:
        """
        Feature dict in exactly the naming `model_trainer.predict()` expects.

        Bridges the one naming difference between this dataclass and the
        trained model's feature columns: `a`/`b` here are `a_star`/`b_star`
        there (matching the dataset CSV schema).
        """
        return {
            "R": self.R, "G": self.G, "B": self.B,
            "L": self.L, "a_star": self.a, "b_star": self.b,
            "delta_E": self.delta_E,
            "H": self.H, "S": self.S, "V": self.V,
            "L_corr": self.L_corr, "a_corr": self.a_corr, "b_corr": self.b_corr,
            "delta_E_corr": self.delta_E_corr,
        }


# ---------------------------------------------------------------------------
# Color math utilities
# ---------------------------------------------------------------------------

# sRGB -> linear RGB
def _linearize(c: np.ndarray) -> np.ndarray:
    """Apply inverse sRGB gamma correction."""
    mask = c <= 0.04045
    linear = np.where(mask, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return linear


def rgb_to_xyz(R: float, G: float, B: float) -> Tuple[float, float, float]:
    """
    Convert sRGB (0-255) to CIE XYZ (D65 illuminant).
    Matrix from se3c02793 paper Eq.(1):
    [X]   [0.412453  0.357580  0.180423] [R]
    [Y] = [0.212671  0.715160  0.072169] [G]
    [Z]   [0.019334  0.119193  0.950227] [B]
    """
    rgb = np.array([R, G, B], dtype=np.float64) / 255.0
    rgb = _linearize(rgb)
    M = np.array([
        [0.412453, 0.357580, 0.180423],
        [0.212671, 0.715160, 0.072169],
        [0.019334, 0.119193, 0.950227],
    ])
    X, Y, Z = M @ rgb
    return X, Y, Z


def xyz_to_lab(X: float, Y: float, Z: float) -> Tuple[float, float, float]:
    """
    Convert CIE XYZ to L*a*b* (D65 reference white).
    Formulas from se3c02793 paper Eq.(2) and Eq.(3).
    """
    # D65 reference white
    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883

    def f(t: float) -> float:
        delta = 6.0 / 29.0
        if t > delta ** 3:
            return t ** (1.0 / 3.0)
        else:
            return t / (3.0 * delta ** 2) + 4.0 / 29.0

    fx = f(X / Xn)
    fy = f(Y / Yn)
    fz = f(Z / Zn)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return L, a, b


def rgb_to_lab(R: float, G: float, B: float) -> Tuple[float, float, float]:
    """Full RGB -> Lab pipeline."""
    X, Y, Z = rgb_to_xyz(R, G, B)
    return xyz_to_lab(X, Y, Z)


# ---------------------------------------------------------------------------
# CANONICAL HSV CONVENTION
# ---------------------------------------------------------------------------
# H in DEGREES on [0, 360), S and V on [0, 1].
#
# This is the single source of truth for the H/S/V model features. Every
# producer in the pipeline must go through `rgb_to_hsv` so that training data
# and inference features live on the same scale:
#
#   demo_simulator.simulate_strip_color()  -> rgb_to_hsv()  -> dataset CSV
#   image_processor.process_strip_image()  -> rgb_to_hsv()  -> predict()
#
# Do NOT feed `cv2.cvtColor(..., COLOR_BGR2HSV)` output into the H/S/V
# features. On uint8 input OpenCV packs hue into 0-179 (half-degrees) and
# S/V into 0-255, which is half-scale in H relative to this convention.
# OpenCV's HSV is still used internally for ROI *masking*, where its own
# scale is self-consistent and never reaches the model.
#
# Averaging matters too: HSV is computed from the already-averaged mean RGB of
# the ROI, not by averaging an HSV image channel-wise. Hue is an angle, so a
# naive channel mean is wrong near the 0/360 wrap.
# ---------------------------------------------------------------------------

def rgb_to_hsv(R: float, G: float, B: float) -> Tuple[float, float, float]:
    """
    Convert sRGB (0-255) to HSV in the canonical convention:
    H in degrees [0, 360), S in [0, 1], V in [0, 1].
    """
    r, g, b = R / 255.0, G / 255.0, B / 255.0
    V = max(r, g, b)
    chroma = V - min(r, g, b)
    S = (chroma / V) if V > 0 else 0.0

    if chroma == 0:
        H = 0.0
    elif V == r:
        H = 60.0 * (((g - b) / chroma) % 6.0)
    elif V == g:
        H = 60.0 * (((b - r) / chroma) + 2.0)
    else:
        H = 60.0 * (((r - g) / chroma) + 4.0)

    return float(H % 360.0), float(S), float(V)


def compute_delta_E2000(
    L1: float, a1: float, b1: float,
    L2: float, a2: float, b2: float,
) -> float:
    """
    CIE DE2000 color difference formula.
    Returns deltaE - the perceptual color distance between two Lab colors.
    Lower = more similar; higher = more different (strip has changed more).
    Reference: Sharma et al. 2005, implemented per se3c02793 paper.
    """
    # Weighting factors
    kL, kC, kH = 1.0, 1.0, 1.0

    # Step 1: compute C*ab
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)
    C_avg = (C1 + C2) / 2.0

    C_avg7 = C_avg**7
    G = 0.5 * (1.0 - np.sqrt(C_avg7 / (C_avg7 + 25.0**7)))

    a1p = a1 * (1 + G)
    a2p = a2 * (1 + G)
    C1p = np.sqrt(a1p**2 + b1**2)
    C2p = np.sqrt(a2p**2 + b2**2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360

    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2.0))

    Lp_avg = (L1 + L2) / 2.0
    Cp_avg = (C1p + C2p) / 2.0

    if C1p * C2p == 0:
        Hp_avg = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        Hp_avg = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        Hp_avg = (h1p + h2p + 360) / 2.0
    else:
        Hp_avg = (h1p + h2p - 360) / 2.0

    T = (1
         - 0.17 * np.cos(np.radians(Hp_avg - 30))
         + 0.24 * np.cos(np.radians(2 * Hp_avg))
         + 0.32 * np.cos(np.radians(3 * Hp_avg + 6))
         - 0.20 * np.cos(np.radians(4 * Hp_avg - 63)))

    SL = 1 + 0.015 * (Lp_avg - 50)**2 / np.sqrt(20 + (Lp_avg - 50)**2)
    SC = 1 + 0.045 * Cp_avg
    SH = 1 + 0.015 * Cp_avg * T

    Cp_avg7 = Cp_avg**7
    RC = 2.0 * np.sqrt(Cp_avg7 / (Cp_avg7 + 25.0**7))
    d_theta = 30 * np.exp(-((Hp_avg - 275) / 25)**2)
    RT = -np.sin(np.radians(2 * d_theta)) * RC

    delta_E = np.sqrt(
        (dLp / (kL * SL))**2 +
        (dCp / (kC * SC))**2 +
        (dHp / (kH * SH))**2 +
        RT * (dCp / (kC * SC)) * (dHp / (kH * SH))
    )
    return float(delta_E)


# ---------------------------------------------------------------------------
# Baseline (fresh / unexposed strip) reference Lab values
# Copper acetate paper: blue-green color before H2S exposure
# These values can be recalibrated in calibrate_baseline()
# ---------------------------------------------------------------------------
BASELINE_LAB = (70.0, -15.0, -10.0)   # L*, a*, b* of fresh copper-acetate strip


def calibrate_baseline(fresh_strip_image_path: str) -> Tuple[float, float, float]:
    """
    Measure the Lab of a known fresh strip and update the baseline.
    Call once at the start of a calibration session.
    """
    img = cv2.imread(fresh_strip_image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot open: {fresh_strip_image_path}")
    roi = detect_strip_roi(img)
    if roi is None:
        log.warning("Baseline calibration: no ROI detected, measuring the whole frame.")
        region = img
    else:
        x, y, w, h = _inset(roi, 0.15)
        region = img[y:y+h, x:x+w]
    R, G, B = _mean_rgb(region)
    L, a, b = rgb_to_lab(R, G, B)
    log.info(f"Calibrated baseline: L={L:.2f} a={a:.2f} b={b:.2f}")
    return L, a, b



# ---------------------------------------------------------------------------
# Reference card color correction (known-patch least-squares method)
# ---------------------------------------------------------------------------
#
# STATUS / LIMITATION — read before relying on this.
#
# The maths below is real and is now genuinely wired into the pipeline: pass
# `measured_patches` (or a prebuilt `correction_matrix`) to
# process_strip_image() / process_strip_array() and the correction is applied,
# with `StripReading.lighting_corrected` set to True.
#
# What is MISSING is the automatic half: there is no reference-card *detector*
# in this repository. Nothing locates the printed patches in a photo and
# measures their Lab values. Until that exists, `measured_patches` has to be
# supplied by the caller, so in the default path no correction runs and
# `lighting_corrected` is False, `L_corr == L`, `delta_E_corr == delta_E`.
#
# The REFERENCE_PATCHES_LAB values below are the *target* Lab values of an
# ideal printed card under D65. They are design constants for a card that has
# not been printed and colorimetrically measured yet. Treat them as
# provisional: once a real card exists, measure it and update these, which is
# a recalibration, not a refactor.
#
# Deliberately NOT done here: inventing a plausible-looking correction (e.g.
# grey-world white balance) and presenting it as reference-card calibration.
# That would change the numbers without improving accuracy and would misreport
# what the system does.
# ---------------------------------------------------------------------------

# Target Lab values for the 4 reference patches on the printed colour card.
# Ideal D65 values; provisional until a physical card is measured.
REFERENCE_PATCHES_LAB = {
    "white":  (95.0,  0.0,   0.0),
    "grey":   (50.0,  0.0,   0.0),
    "cyan":   (70.0, -30.0, -15.0),
    "brown":  (35.0,  20.0,  25.0),
}


def build_color_correction_matrix(
    measured_patches: dict,
    reference_patches: dict = REFERENCE_PATCHES_LAB,
) -> np.ndarray:
    """
    Compute a 3x4 affine Lab correction matrix by least squares.

    Solves for M minimising ||M @ [L,a,b,1] - reference|| over the supplied
    patches, so the measured card maps onto its known target values and the
    same transform can then be applied to the strip.

    Args:
        measured_patches: ``{"white": (L,a,b), "grey": (L,a,b), ...}`` measured
            from the card in the same photo as the strip.
        reference_patches: Target Lab values (defaults to
            :data:`REFERENCE_PATCHES_LAB`).

    Returns:
        A (3, 4) matrix M such that ``corrected = M @ [L, a, b, 1]``.

    Raises:
        KeyError: if a patch named in ``reference_patches`` is missing from
            ``measured_patches``.
        ValueError: if fewer than 4 patches are supplied — an affine Lab fit
            has 4 unknowns per output channel, so 3 or fewer is underdetermined
            and would silently produce a garbage transform.
    """
    keys = list(reference_patches.keys())
    missing = [k for k in keys if k not in measured_patches]
    if missing:
        raise KeyError(f"measured_patches is missing patches: {missing}")
    if len(keys) < 4:
        raise ValueError(
            f"Need at least 4 reference patches for an affine Lab fit, got {len(keys)}."
        )

    src = np.array([list(measured_patches[k]) + [1.0] for k in keys])   # Nx4
    dst = np.array([list(reference_patches[k]) for k in keys])          # Nx3
    M, _, _, _ = np.linalg.lstsq(src, dst, rcond=None)                  # 4x3
    return M.T   # 3x4



def apply_color_correction(
    L: float, a: float, b: float, M: np.ndarray
) -> Tuple[float, float, float]:
    """Apply the 3x4 correction matrix to a Lab measurement."""
    v = np.array([L, a, b, 1.0])
    Lc, ac, bc = M @ v
    return float(Lc), float(ac), float(bc)


# ---------------------------------------------------------------------------
# ROI (Region of Interest) detection
# ---------------------------------------------------------------------------
#
# CURRENT ARCHITECTURE: marker-independent detection.
#
# There is no ArUco / fiducial-marker detection in this repository, and none is
# simulated here. The strip is located purely from image content. If printed
# markers are added to the wristband or reference card later, a marker-based
# detector should be preferred and this one kept as the fallback.
#
# Why not hue thresholds: the copper-acetate strip sweeps continuously from
# blue-green (fresh) through desaturated olive to grey-brown (exposed). Any
# fixed pair of hue windows leaves a dead zone mid-transition — the previous
# implementation used hue 80-150 and <=35 (OpenCV 0-179 scale) and silently
# missed the whole 20-70 ppm.hr band, i.e. exactly the DGMS warning region.
#
# Instead the strip is found as "the region that differs from the background",
# which holds at every point in the transition:
#   1. Estimate background colour from a border frame of the image.
#   2. Build a per-pixel Lab distance-from-background map (hue-agnostic).
#   3. Threshold it (Otsu) and clean up morphologically.
#   4. Score every contour on shape + uniformity + contrast, and keep the best.
# Saturation- and edge-based candidate generators run as additional proposals
# so a single failing segmentation cannot lose the strip.
# ---------------------------------------------------------------------------

# A candidate must beat this combined score to count as a real detection.
ROI_MIN_SCORE = 0.45

# Plausible geometry for a strip bounding box.
_ROI_MIN_AREA_FRAC = 0.002   # at least 0.2% of the frame
_ROI_MAX_AREA_FRAC = 0.75    # more than this is probably the whole scene
_ROI_MAX_ASPECT = 12.0


def _lab_image(bgr: np.ndarray) -> np.ndarray:
    """OpenCV Lab image as float32. Used only for distances, never for features."""
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def _background_lab(lab: np.ndarray, border_frac: float = 0.12) -> np.ndarray:
    """
    Estimate the background colour from a frame around the image edge.

    Assumes the strip is not flush against the border, which is what the
    capture guidance asks of the user anyway.
    """
    h, w = lab.shape[:2]
    bh, bw = max(1, int(h * border_frac)), max(1, int(w * border_frac))
    frame = np.concatenate([
        lab[:bh, :, :].reshape(-1, 3),
        lab[-bh:, :, :].reshape(-1, 3),
        lab[:, :bw, :].reshape(-1, 3),
        lab[:, -bw:, :].reshape(-1, 3),
    ], axis=0)
    return np.median(frame, axis=0)


def _candidates_from_mask(mask: np.ndarray, method: str) -> list:
    """Clean a binary mask and return (bbox, contour, method) proposals."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 4 or h < 4:
            continue
        out.append(((x, y, w, h), c, method))
    return out


def _propose_rois(bgr: np.ndarray, lab: np.ndarray, bg_lab: np.ndarray) -> list:
    """
    Generate ROI candidates from three independent, hue-agnostic cues.

    Using several cues means a strip that one segmentation misses (e.g. a
    near-neutral mid-transition strip on a neutral background) can still be
    recovered by another.
    """
    candidates = []

    # Cue 1 — distance from background in Lab. Works at any hue because it
    # asks "is this pixel unlike the surround?", not "is this pixel green?".
    dist = np.linalg.norm(lab - bg_lab.reshape(1, 1, 3), axis=2)
    dmax = float(dist.max())
    if dmax > 1e-6:
        dist_u8 = np.clip(dist / dmax * 255.0, 0, 255).astype(np.uint8)
        _, mask = cv2.threshold(dist_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates += _candidates_from_mask(mask, "bg_distance_otsu")

    # Cue 2 — chromatic content. Catches a coloured strip on a neutral
    # background even when its lightness matches the surround.
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    if int(sat.max()) > 30:
        _, mask = cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates += _candidates_from_mask(mask, "saturation_otsu")

    # Cue 3 — edges. Purely geometric; independent of colour entirely.
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(grey, (5, 5), 0)
    med = float(np.median(blurred))
    edges = cv2.Canny(blurred, max(10.0, 0.66 * med), max(30.0, 1.33 * med))
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    candidates += _candidates_from_mask(edges, "edge_contour")

    return candidates


def _inset(bbox: Tuple[int, int, int, int], frac: float = 0.15
           ) -> Tuple[int, int, int, int]:
    """
    Shrink a bbox toward its centre.

    Sampling colour from the inset avoids the antialiased boundary and any
    shadow line at the strip edge, both of which bias the mean toward the
    background.
    """
    x, y, w, h = bbox
    dx, dy = int(w * frac), int(h * frac)
    nx, ny = x + dx, y + dy
    nw, nh = max(1, w - 2 * dx), max(1, h - 2 * dy)
    return nx, ny, nw, nh


def _score_candidate(bbox, contour, lab: np.ndarray, bg_lab: np.ndarray,
                     image_area: float) -> Tuple[float, dict]:
    """
    Score an ROI candidate in [0, 1] on four hue-independent criteria.

    A real strip is a compact, roughly rectangular, internally uniform patch
    that contrasts with its surround. Background blobs fail at least one.
    """
    x, y, w, h = bbox
    bbox_area = float(w * h)
    area_frac = bbox_area / image_area
    long_side, short_side = max(w, h), max(1, min(w, h))
    aspect = long_side / short_side

    # Hard geometric rejects.
    if not (_ROI_MIN_AREA_FRAC <= area_frac <= _ROI_MAX_AREA_FRAC):
        return 0.0, {"reject": f"area_frac={area_frac:.4f}"}
    if aspect > _ROI_MAX_ASPECT:
        return 0.0, {"reject": f"aspect={aspect:.2f}"}

    # 1. Rectangularity — contour fills its bounding box.
    fill = float(cv2.contourArea(contour)) / bbox_area if bbox_area > 0 else 0.0
    fill = min(1.0, fill)

    # 2. Aspect plausibility — flat ramp; a strip is oblong but a head-on
    #    square crop is still acceptable.
    aspect_score = 1.0 if aspect <= 6.0 else max(0.0, 1.0 - (aspect - 6.0) / 6.0)

    # 3. Internal uniformity — the strip is one colour, so Lab spread is small.
    inner = _inset(bbox, 0.15)
    ix, iy, iw, ih = inner
    patch = lab[iy:iy + ih, ix:ix + iw]
    if patch.size == 0:
        return 0.0, {"reject": "empty_patch"}
    spread = float(np.mean(np.std(patch.reshape(-1, 3), axis=0)))
    uniformity = float(np.clip(1.0 - spread / 25.0, 0.0, 1.0))

    # 4. Contrast against the background estimate.
    patch_mean = patch.reshape(-1, 3).mean(axis=0)
    contrast = float(np.linalg.norm(patch_mean - bg_lab))
    contrast_score = float(np.clip(contrast / 30.0, 0.0, 1.0))

    score = (0.30 * fill + 0.15 * aspect_score
             + 0.30 * uniformity + 0.25 * contrast_score)

    return float(np.clip(score, 0.0, 1.0)), {
        "fill": round(fill, 3),
        "aspect": round(aspect, 2),
        "uniformity": round(uniformity, 3),
        "contrast": round(contrast, 2),
        "area_frac": round(area_frac, 4),
    }


def detect_strip_roi(
    image: np.ndarray,
    debug: bool = False,
    return_details: bool = False,
):
    """
    Locate the colorimetric strip in a photo, independent of its hue.

    Generates candidates from background-distance, saturation and edge cues,
    then scores each on rectangularity, aspect, internal uniformity and
    contrast against the background. The best candidate wins if it clears
    ``ROI_MIN_SCORE``.

    Args:
        image: BGR image array.
        debug: Save an annotated ``debug_roi.jpg``.
        return_details: If True return ``(bbox, details)`` instead of ``bbox``.

    Returns:
        ``(x, y, w, h)`` or ``None`` when nothing scored well enough.
        With ``return_details=True``, also a dict carrying the winning method,
        score, per-criterion breakdown and the number of candidates examined.
    """
    lab = _lab_image(image)
    bg_lab = _background_lab(lab)
    image_area = float(image.shape[0] * image.shape[1])

    candidates = _propose_rois(image, lab, bg_lab)

    best_bbox, best_score, best_method, best_parts = None, 0.0, "none", {}
    for bbox, contour, method in candidates:
        score, parts = _score_candidate(bbox, contour, lab, bg_lab, image_area)
        if score > best_score:
            best_bbox, best_score, best_method, best_parts = bbox, score, method, parts

    details = {
        "n_candidates": len(candidates),
        "score": round(best_score, 4),
        "method": best_method,
        "parts": best_parts,
    }

    if best_bbox is None or best_score < ROI_MIN_SCORE:
        reason = (f"no candidate reached ROI_MIN_SCORE={ROI_MIN_SCORE} "
                  f"(best={best_score:.3f} via {best_method})")
        log.warning("ROI detection: %s — falling back to center crop.", reason)
        details["reason"] = reason
        return (None, details) if return_details else None

    if debug:
        dbg = image.copy()
        x, y, w, h = best_bbox
        ix, iy, iw, ih = _inset(best_bbox, 0.15)
        cv2.rectangle(dbg, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.rectangle(dbg, (ix, iy), (ix + iw, iy + ih), (0, 200, 255), 1)
        cv2.imwrite("debug_roi.jpg", dbg)
        log.info("ROI debug image saved: debug_roi.jpg")

    log.info("ROI detected via %s (score=%.3f): x=%d y=%d w=%d h=%d",
             best_method, best_score, *best_bbox)
    details["reason"] = "ok"
    return (best_bbox, details) if return_details else best_bbox


def _center_crop(image: np.ndarray, fraction: float = 0.4) -> np.ndarray:
    """Fall-back: crop the central fraction of the image."""
    h, w = image.shape[:2]
    cy, cx = h // 2, w // 2
    dh, dw = int(h * fraction / 2), int(w * fraction / 2)
    return image[cy-dh:cy+dh, cx-dw:cx+dw]


def _mean_rgb(region: np.ndarray) -> Tuple[float, float, float]:
    """
    Representative (R, G, B) of a BGR region, using the per-channel median.

    The median is preferred over the mean because a specular highlight or a
    few dust pixels shift a mean noticeably while leaving the median of a
    uniform patch intact.
    """
    flat = region.reshape(-1, 3).astype(np.float64)
    B, G, R = np.median(flat, axis=0)
    return float(R), float(G), float(B)



# ---------------------------------------------------------------------------
# Main processing function
# ---------------------------------------------------------------------------

def process_strip_image(
    image_path: str,
    baseline_lab: Tuple[float, float, float] = BASELINE_LAB,
    correction_matrix: Optional[np.ndarray] = None,
    measured_patches: Optional[dict] = None,
    debug: bool = False,
) -> StripReading:
    """
    Full pipeline: image file --> StripReading dataclass.

    Args:
        image_path: Path to the strip photo.
        baseline_lab: Lab of a fresh (unexposed) strip for deltaE reference.
        correction_matrix: Optional pre-built 3x4 Lab correction matrix.
        measured_patches: Optional ``{"white": (L,a,b), ...}`` measured from a
            reference card in this same photo; a correction matrix is built
            from it via :func:`build_color_correction_matrix`. Ignored when
            ``correction_matrix`` is given. See
            :func:`build_color_correction_matrix` for the honest limits here —
            there is no automatic card detector, so patches must be supplied
            by the caller.
        debug: If True, saves a debug ROI image.

    Returns:
        StripReading with all colour metrics plus ROI and lighting diagnostics.
        Inspect ``roi_detected`` / ``roi_confidence`` before trusting a reading,
        and ``lighting_corrected`` to know whether normalization actually ran.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot open image: {image_path}")

    reading = process_strip_array(
        img,
        baseline_lab=baseline_lab,
        correction_matrix=correction_matrix,
        measured_patches=measured_patches,
        debug=debug,
    )
    return reading


def process_strip_array(
    image: np.ndarray,
    baseline_lab: Tuple[float, float, float] = BASELINE_LAB,
    correction_matrix: Optional[np.ndarray] = None,
    measured_patches: Optional[dict] = None,
    debug: bool = False,
) -> StripReading:
    """
    Same pipeline as :func:`process_strip_image` but on an in-memory BGR array.

    Split out so a caller holding decoded image bytes (a future upload
    endpoint, or a test that renders frames) does not have to write a
    temporary file first.
    """
    if image is None or image.size == 0:
        raise ValueError("Empty image passed to process_strip_array().")

    # 1. ROI detection (hue-agnostic; see detect_strip_roi)
    roi, roi_details = detect_strip_roi(image, debug=debug, return_details=True)

    if roi is None:
        # Fallback: centre crop. Deliberately LOW confidence — the colour here
        # may include background, so downstream code must be able to tell this
        # apart from a real detection.
        region = _center_crop(image)
        roi_detected = False
        roi_method = "center_crop_fallback"
        roi_confidence = 0.25
        roi_bbox = None
        roi_reason = roi_details.get("reason", "roi detection failed")
    else:
        # Sample from an inset of the bbox to avoid the antialiased border.
        x, y, w, h = _inset(roi, 0.15)
        region = image[y:y + h, x:x + w]
        roi_detected = True
        roi_method = roi_details.get("method", "contour_score")
        roi_confidence = float(roi_details.get("score", 1.0))
        roi_bbox = roi
        roi_reason = "ok"

    if region.size == 0:
        region = _center_crop(image)
        roi_detected = False
        roi_method = "center_crop_fallback"
        roi_confidence = 0.25
        roi_bbox = None
        roi_reason = "roi bbox collapsed to an empty region"

    # 2. Representative RGB (median — robust to highlights)
    R, G, B = _mean_rgb(region)

    # 3. HSV in the canonical convention, computed FROM the representative RGB.
    #    Never from a channel-wise mean of an OpenCV HSV image: that would be
    #    half-scale in hue and wrong across the hue wrap. See rgb_to_hsv.
    H, S, V = rgb_to_hsv(R, G, B)

    # 4. RGB -> Lab
    L, a, b = rgb_to_lab(R, G, B)

    # 5. Raw deltaE vs baseline
    bL, ba, bb = baseline_lab
    delta_E = compute_delta_E2000(bL, ba, bb, L, a, b)

    # 6. Lighting correction. Only genuinely applied when the caller supplies
    #    reference-card information; otherwise the raw values pass through and
    #    `lighting_corrected` stays False so nothing claims otherwise.
    M = correction_matrix
    correction_method = "none"
    if M is None and measured_patches:
        try:
            M = build_color_correction_matrix(measured_patches)
            correction_method = "reference_card_lstsq"
        except Exception as e:                              # noqa: BLE001
            log.warning("Could not build correction matrix (%s); using raw Lab.", e)
            M = None
    elif M is not None:
        correction_method = "caller_supplied_matrix"

    if M is not None:
        L_corr, a_corr, b_corr = apply_color_correction(L, a, b, M)
        delta_E_corr = compute_delta_E2000(bL, ba, bb, L_corr, a_corr, b_corr)
        lighting_corrected = True
    else:
        L_corr, a_corr, b_corr = L, a, b
        delta_E_corr = delta_E
        lighting_corrected = False

    # 7. Overall confidence. Driven by ROI reliability, since that is the
    #    dominant error source: a bad ROI averages in background and skews
    #    every downstream feature. Uncorrected lighting is a smaller, known
    #    penalty.
    confidence = roi_confidence
    if not lighting_corrected:
        confidence *= 0.9
    confidence = float(np.clip(confidence, 0.0, 1.0))

    reading = StripReading(
        R=R, G=G, B=B,
        L=L, a=a, b=b,
        delta_E=delta_E,
        H=H, S=S, V=V,
        L_corr=L_corr, a_corr=a_corr, b_corr=b_corr,
        delta_E_corr=delta_E_corr,
        confidence=confidence,
        roi_detected=roi_detected,
        roi_method=roi_method,
        roi_confidence=roi_confidence,
        roi_bbox=roi_bbox,
        roi_reason=roi_reason,
        lighting_corrected=lighting_corrected,
        correction_method=correction_method,
    )

    log.info(
        "Processed: R=%.1f G=%.1f B=%.1f | L=%.2f a=%.2f b=%.2f | "
        "H=%.1fdeg S=%.3f V=%.3f | deltaE=%.3f deltaE_corr=%.3f | "
        "roi=%s(%s, conf=%.3f) lighting_corrected=%s",
        R, G, B, L, a, b, H, S, V, delta_E, delta_E_corr,
        roi_detected, roi_method, roi_confidence, lighting_corrected,
    )
    return reading



# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("image_processor.py — Self-Test")
    print("=" * 60)

    # Test 1: Math correctness — known RGB -> Lab
    print("\n[TEST 1] RGB -> Lab conversion")
    test_cases = [
        ((255, 255, 255), (100.0,  0.0,   0.0),   "White"),
        ((0,   0,   0),   (0.0,    0.0,   0.0),   "Black"),
        ((255, 0,   0),   (53.23, 80.11, 67.22),  "Red"),
        ((0,   255, 0),   (87.74,-86.18, 83.18),  "Green"),
        ((0,   0,   255), (32.30, 79.19,-107.86), "Blue"),
    ]
    all_pass = True
    for (R, G, B), (eL, ea, eb), name in test_cases:
        L, a, b = rgb_to_lab(R, G, B)
        tol = 2.0
        ok = abs(L-eL) < tol and abs(a-ea) < tol and abs(b-eb) < tol
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status} {name}: got L={L:.2f} a={a:.2f} b={b:.2f} | expected ~L={eL} a={ea} b={eb}")

    # Test 2: deltaE — identical colors should give 0
    print("\n[TEST 2] CIE DE2000 deltaE")
    dE_identical = compute_delta_E2000(50, 10, 20, 50, 10, 20)
    dE_ok = dE_identical < 0.001
    if not dE_ok:
        all_pass = False
    print(f"  Identical colors deltaE = {dE_identical:.6f}  (expected: 0.0) {'PASS' if dE_ok else 'FAIL'}")

    # Test 3: canonical HSV convention (H degrees 0-360, S/V 0-1)
    print("\n[TEST 3] Canonical HSV (rgb_to_hsv)")
    hsv_cases = [
        ((255, 0, 0),     (0.0,   1.0, 1.0),  "Red"),
        ((0, 255, 0),     (120.0, 1.0, 1.0),  "Green"),
        ((0, 0, 255),     (240.0, 1.0, 1.0),  "Blue"),
        ((0, 255, 255),   (180.0, 1.0, 1.0),  "Cyan"),
        ((255, 255, 255), (0.0,   0.0, 1.0),  "White"),
        ((0, 0, 0),       (0.0,   0.0, 0.0),  "Black"),
    ]
    for (R, G, B), (eH, eS, eV), name in hsv_cases:
        H, S, V = rgb_to_hsv(R, G, B)
        ok = abs(H - eH) < 0.5 and abs(S - eS) < 0.01 and abs(V - eV) < 0.01
        if not ok:
            all_pass = False
        print(f"  {'PASS' if ok else 'FAIL'} {name}: got H={H:.1f} S={S:.3f} V={V:.3f} "
              f"| expected H={eH} S={eS} V={eV}")

    # Hue must span the full 0-360 range, not OpenCV's 0-179 half-degrees.
    h_green, _, _ = rgb_to_hsv(0, 255, 0)
    scale_ok = abs(h_green - 120.0) < 0.5
    if not scale_ok:
        all_pass = False
    print(f"  {'PASS' if scale_ok else 'FAIL'} hue is in degrees 0-360 "
          f"(pure green = {h_green:.1f}, not 60)")

    # Test 4: ROI detection across the full colour transition
    print("\n[TEST 4] ROI detection across the exposure gradient")
    _strip_colors = [
        (0,   (80, 160, 140)),    # fresh blue-green
        (20,  (98, 149, 129)),    # previously in the hue dead zone
        (35,  (108, 142, 122)),   # previously in the hue dead zone
        (50,  (117, 137, 117)),   # previously in the hue dead zone
        (68,  (126, 131, 111)),   # previously in the hue dead zone
        (88,  (133, 127, 107)),   # exposed grey-brown
        (120, (142, 121, 101)),   # saturated exposure
    ]
    roi_pass = 0
    for dose, (R, G, B) in _strip_colors:
        canvas = np.full((400, 600, 3), 210, np.uint8)
        cv2.rectangle(canvas, (150, 160), (450, 240), (B, G, R), -1)
        bbox, det = detect_strip_roi(canvas, return_details=True)
        ok = bbox is not None
        if ok:
            roi_pass += 1
        else:
            all_pass = False
        print(f"  {'PASS' if ok else 'FAIL'} dose~{dose:>3} ppm.hr: "
              f"{'bbox=' + str(bbox) if ok else 'NOT DETECTED'} "
              f"(score={det['score']:.3f}, {det['method']})")
    print(f"  -> {roi_pass}/{len(_strip_colors)} detected")

    # Test 5: Process image if provided on command line
    if len(sys.argv) > 1:
        img_path = sys.argv[1]
        print(f"\n[TEST 5] Processing image: {img_path}")
        try:
            reading = process_strip_image(img_path, debug=True)
            print(f"  R={reading.R:.1f} G={reading.G:.1f} B={reading.B:.1f}")
            print(f"  L={reading.L:.2f} a={reading.a:.2f} b={reading.b:.2f}")
            print(f"  H={reading.H:.1f}deg S={reading.S:.3f} V={reading.V:.3f}")
            print(f"  deltaE = {reading.delta_E:.3f}")
            print(f"  roi_detected={reading.roi_detected} method={reading.roi_method} "
                  f"roi_confidence={reading.roi_confidence:.3f}")
            print(f"  lighting_corrected={reading.lighting_corrected} "
                  f"({reading.correction_method})")
            print(f"  overall confidence={reading.confidence:.3f}")
        except FileNotFoundError as e:
            print(f"  {e}")
    else:
        print("\n[TEST 5] No image provided (pass path as argument to test on a real photo)")

    print("\n" + "=" * 60)
    print(f"Self-test: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print("=" * 60)
    sys.exit(0 if all_pass else 1)
