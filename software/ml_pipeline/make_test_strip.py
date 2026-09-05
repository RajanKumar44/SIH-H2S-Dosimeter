"""
make_test_strip.py
==================
Generate synthetic strip photographs for testing ``POST /readings/scan``
end-to-end **without physical hardware**.

Why this exists
---------------
The full software flow (phone -> upload -> ROI detect -> ΔE2000 -> ML -> dose ->
alert -> history) can only be exercised with a real JPEG. No H₂S wristband or
strip dataset exists yet, so this script renders an image that *looks like* a
photographed strip: a coloured patch on a neutral background, with mild
per-pixel sensor noise and a soft lighting gradient so ROI detection has
something realistic to find.

The patch colour comes from ``demo_simulator.simulate_strip_color`` — the SAME
physics-based copper-acetate → copper-sulfide model used to build the training
set — so the rendered colour is consistent with the model's input distribution.
This is a **software test fixture**, not a calibrated optical target: the doses
it recovers demonstrate that the pipeline runs correctly, and say nothing about
real-world accuracy.

Usage
-----
    python make_test_strip.py                      # a default 30 ppm.hr strip
    python make_test_strip.py --dose 85 --out danger.jpg
    python make_test_strip.py --sweep 0,25,50,75,100   # one file per dose
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import argparse
from pathlib import Path

import cv2
import numpy as np

from demo_simulator import simulate_strip_color

OUT_DIR = Path(__file__).resolve().parent / "sample_images"


def render_strip(
    dose_ppm_hr: float,
    width: int = 900,
    height: int = 600,
    seed: int | None = None,
) -> tuple[np.ndarray, dict]:
    """
    Render a synthetic "photo" of an exposed strip.

    Returns ``(bgr_image, truth)`` where ``truth`` holds the colour features the
    simulator produced, so a caller can compare them against what the pipeline
    recovers from the pixels.
    """
    rng = np.random.default_rng(seed)
    truth = simulate_strip_color(dose_ppm_hr)
    R, G, B = truth["R"], truth["G"], truth["B"]

    # Neutral mid-grey surround — a bench/table, not pure white, so the strip
    # is the most saturated region in frame and ROI detection is meaningful.
    img = np.full((height, width, 3), 170, dtype=np.float32)

    # The strip patch: a generous centred rectangle (a phone held over a
    # wristband). OpenCV is BGR.
    x0, x1 = int(width * 0.22), int(width * 0.78)
    y0, y1 = int(height * 0.28), int(height * 0.72)
    img[y0:y1, x0:x1] = np.array([B, G, R], dtype=np.float32)

    # Soft diagonal lighting gradient (±6%) — real photos are never uniform.
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    grad = 1.0 + 0.06 * ((xx / width) - 0.5 + (yy / height) - 0.5)
    img *= grad[:, :, None]

    # Mild sensor noise.
    img += rng.normal(0.0, 2.0, img.shape).astype(np.float32)

    return np.clip(img, 0, 255).astype(np.uint8), truth


def write_strip(dose: float, out_path: Path, seed: int | None = None) -> dict:
    img, truth = render_strip(dose, seed=seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), img, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
        raise RuntimeError(f"Failed to write {out_path}")
    print(f"  [OK] {out_path.name:24s} dose={dose:6.1f} ppm.hr  "
          f"RGB=({truth['R']:.0f},{truth['G']:.0f},{truth['B']:.0f})  "
          f"deltaE={truth['delta_E']:.2f}")
    return truth


def main() -> int:
    ap = argparse.ArgumentParser(description="Render synthetic H2S strip photos.")
    ap.add_argument("--dose", type=float, default=30.0, help="Dose in ppm.hr.")
    ap.add_argument("--out", type=str, default=None, help="Output JPEG path.")
    ap.add_argument("--sweep", type=str, default=None,
                    help="Comma-separated doses; writes one file each.")
    ap.add_argument("--seed", type=int, default=None, help="Noise seed.")
    args = ap.parse_args()

    print("=" * 62)
    print("  Synthetic strip renderer (software test fixture)")
    print("=" * 62)

    if args.sweep:
        doses = [float(d) for d in args.sweep.split(",") if d.strip()]
        for d in doses:
            write_strip(d, OUT_DIR / f"strip_{int(round(d)):03d}ppmhr.jpg", args.seed)
    else:
        out = Path(args.out) if args.out else OUT_DIR / f"strip_{int(round(args.dose)):03d}ppmhr.jpg"
        write_strip(args.dose, out, args.seed)

    print("=" * 62)
    print("  NOTE: synthetic fixture — demonstrates the software path only.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
