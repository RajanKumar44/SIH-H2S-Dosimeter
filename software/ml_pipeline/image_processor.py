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
    # HSV
    H: float
    S: float
    V: float
    # Lighting-corrected Lab values (after reference card normalization)
    L_corr: float
    a_corr: float
    b_corr: float
    delta_E_corr: float
    # Confidence (0-1): how well the ROI was detected
    confidence: float = 1.0


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
        region = img
    else:
        x, y, w, h = roi
        region = img[y:y+h, x:x+w]
    R, G, B = _mean_rgb(region)
    L, a, b = rgb_to_lab(R, G, B)
    log.info(f"Calibrated baseline: L={L:.2f} a={a:.2f} b={b:.2f}")
    return L, a, b


# ---------------------------------------------------------------------------
# Reference card color correction (grey-world / known-patch method)
# ---------------------------------------------------------------------------

# Expected Lab values for the 4 reference patches on the printed color card
# These are ideal values for a D65 illuminant; the card correction
# adjusts for the actual illuminant captured by the camera.
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
    Compute a 3x4 affine correction matrix in Lab space using least squares.
    measured_patches: {"white": (L,a,b), "grey": (L,a,b), ...}
    Returns a (3,4) matrix M such that corrected = M @ [L, a, b, 1]
    """
    keys = list(reference_patches.keys())
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

def detect_strip_roi(
    image: np.ndarray,
    debug: bool = False,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Auto-detect the colorimetric strip in a photo.
    Strategy:
      1. Convert to HSV
      2. Threshold for the blue-green (fresh) or brown-grey (exposed) hue range
      3. Find the largest contour that looks like a rectangular strip
      4. Return bounding box (x, y, w, h)

    Returns None if no strip is detected (fall back to full image center crop).
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Blue-green (fresh copper acetate): Hue ~80-150
    mask_fresh = cv2.inRange(hsv, (80, 30, 40), (150, 255, 255))
    # Grey-brown (exposed): Hue ~10-30, low saturation
    mask_exposed = cv2.inRange(hsv, (5, 10, 40), (35, 180, 220))

    combined = cv2.bitwise_or(mask_fresh, mask_exposed)

    # Morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=2)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        log.warning("ROI detection: no contours found, using center crop.")
        return None

    # Pick largest contour that has reasonable aspect ratio for a strip
    best = None
    best_area = 0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        aspect = max(w, h) / max(min(w, h), 1)
        if area > best_area and 1.2 < aspect < 8.0:
            best_area = area
            best = (x, y, w, h)

    if best is None:
        log.warning("ROI detection: no strip-shaped contour, using center crop.")
        return None

    if debug:
        dbg = image.copy()
        x, y, w, h = best
        cv2.rectangle(dbg, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.imwrite("debug_roi.jpg", dbg)
        log.info(f"ROI debug image saved: debug_roi.jpg")

    log.info(f"ROI detected: x={best[0]} y={best[1]} w={best[2]} h={best[3]}")
    return best


def _center_crop(image: np.ndarray, fraction: float = 0.4) -> np.ndarray:
    """Fall-back: crop the central fraction of the image."""
    h, w = image.shape[:2]
    cy, cx = h // 2, w // 2
    dh, dw = int(h * fraction / 2), int(w * fraction / 2)
    return image[cy-dh:cy+dh, cx-dw:cx+dw]


def _mean_rgb(region: np.ndarray) -> Tuple[float, float, float]:
    """Return mean (R, G, B) of a BGR image region."""
    mean_bgr = cv2.mean(region)[:3]
    B, G, R = mean_bgr
    return float(R), float(G), float(B)


# ---------------------------------------------------------------------------
# Main processing function
# ---------------------------------------------------------------------------

def process_strip_image(
    image_path: str,
    baseline_lab: Tuple[float, float, float] = BASELINE_LAB,
    correction_matrix: Optional[np.ndarray] = None,
    debug: bool = False,
) -> StripReading:
    """
    Full pipeline: image file --> StripReading dataclass.

    Args:
        image_path: Path to the strip photo.
        baseline_lab: Lab of a fresh (unexposed) strip for deltaE reference.
        correction_matrix: Optional 3x4 lighting correction matrix.
        debug: If True, saves a debug ROI image.

    Returns:
        StripReading with all color metrics.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot open image: {image_path}")

    # 1. ROI detection
    roi = detect_strip_roi(img, debug=debug)
    confidence = 1.0
    if roi is None:
        region = _center_crop(img)
        confidence = 0.5
    else:
        x, y, w, h = roi
        region = img[y:y+h, x:x+w]

    # 2. Mean RGB
    R, G, B = _mean_rgb(region)

    # 3. HSV
    hsv_region = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    H_mean, S_mean, V_mean = cv2.mean(hsv_region)[:3]

    # 4. RGB -> Lab
    L, a, b = rgb_to_lab(R, G, B)

    # 5. Raw deltaE vs baseline
    bL, ba, bb = baseline_lab
    delta_E = compute_delta_E2000(bL, ba, bb, L, a, b)

    # 6. Lighting correction (if reference card matrix available)
    if correction_matrix is not None:
        L_corr, a_corr, b_corr = apply_color_correction(L, a, b, correction_matrix)
        delta_E_corr = compute_delta_E2000(bL, ba, bb, L_corr, a_corr, b_corr)
    else:
        L_corr, a_corr, b_corr = L, a, b
        delta_E_corr = delta_E

    reading = StripReading(
        R=R, G=G, B=B,
        L=L, a=a, b=b,
        delta_E=delta_E,
        H=float(H_mean), S=float(S_mean / 255.0), V=float(V_mean / 255.0),
        L_corr=L_corr, a_corr=a_corr, b_corr=b_corr,
        delta_E_corr=delta_E_corr,
        confidence=confidence,
    )

    log.info(
        f"Processed: R={R:.1f} G={G:.1f} B={B:.1f} | "
        f"L={L:.2f} a={a:.2f} b={b:.2f} | "
        f"deltaE={delta_E:.3f} | deltaE_corr={delta_E_corr:.3f}"
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
    print(f"  Identical colors deltaE = {dE_identical:.6f}  (expected: 0.0) {'PASS' if dE_identical < 0.001 else 'FAIL'}")

    # Test 3: Process image if provided on command line
    if len(sys.argv) > 1:
        img_path = sys.argv[1]
        print(f"\n[TEST 3] Processing image: {img_path}")
        try:
            reading = process_strip_image(img_path, debug=True)
            print(f"  R={reading.R:.1f} G={reading.G:.1f} B={reading.B:.1f}")
            print(f"  L={reading.L:.2f} a={reading.a:.2f} b={reading.b:.2f}")
            print(f"  deltaE = {reading.delta_E:.3f}  confidence={reading.confidence}")
        except FileNotFoundError as e:
            print(f"  {e}")
    else:
        print("\n[TEST 3] No image provided (pass path as argument to test on a real photo)")

    print("\n" + "=" * 60)
    print(f"Math tests: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print("=" * 60)
