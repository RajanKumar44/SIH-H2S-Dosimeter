"""
dataset_builder.py
==================
Batch-processes a folder of strip photos and builds a labeled CSV dataset.

Usage:
  python dataset_builder.py --images_dir ./sample_images --output datasets/dataset.csv
  python dataset_builder.py --help

CSV schema produced:
  sample_id, image_path, h2s_ppm, exposure_time_min, cumulative_dose_ppm_hr,
  R, G, B, L, a_star, b_star, delta_E, H, S, V,
  L_corr, a_corr, b_corr, delta_E_corr, confidence, notes
"""

import os
import csv
import json
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np
import pandas as pd
from tqdm import tqdm

from image_processor import (
    process_strip_image,
    calibrate_baseline,
    BASELINE_LAB,
    StripReading,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


CSV_COLUMNS = [
    "sample_id", "image_path",
    "h2s_ppm", "exposure_time_min", "cumulative_dose_ppm_hr",
    "R", "G", "B",
    "L", "a_star", "b_star", "delta_E",
    "H", "S", "V",
    "L_corr", "a_corr", "b_corr", "delta_E_corr",
    "confidence",
    # ROI diagnostics — let you filter out samples whose strip was not located
    # before training on them. model_trainer ignores columns it does not use.
    "roi_detected", "roi_method", "roi_confidence",
    "notes",
]



def parse_label_file(label_path: str) -> Dict[str, dict]:
    """
    Load a labels.json file that maps image filename -> experimental conditions.

    Expected format:
    {
        "P001_5ppm_30min.jpg": {"h2s_ppm": 5.0, "exposure_time_min": 30, "notes": ""},
        "P002_10ppm_60min.jpg": {"h2s_ppm": 10.0, "exposure_time_min": 60, "notes": ""},
        ...
    }
    """
    with open(label_path, "r") as f:
        data = json.load(f)
    log.info(f"Loaded {len(data)} labels from {label_path}")
    return data


def parse_label_from_filename(filename: str) -> dict:
    """
    Parse H2S conditions from filename convention:
      P{id}_{ppm}ppm_{min}min[_{notes}].jpg
      e.g. P001_5ppm_30min.jpg  -> h2s_ppm=5.0, exposure_time_min=30
           P002_fresh.jpg       -> h2s_ppm=0.0, exposure_time_min=0
    Returns empty dict if pattern doesn't match.
    """
    stem = Path(filename).stem.lower()
    if "fresh" in stem or "baseline" in stem or "0ppm" in stem:
        return {"h2s_ppm": 0.0, "exposure_time_min": 0, "notes": "fresh"}

    import re
    ppm_match = re.search(r"(\d+(?:\.\d+)?)ppm", stem)
    min_match = re.search(r"(\d+(?:\.\d+)?)min", stem)

    if ppm_match and min_match:
        return {
            "h2s_ppm": float(ppm_match.group(1)),
            "exposure_time_min": float(min_match.group(1)),
            "notes": "",
        }
    return {}


def process_image_folder(
    images_dir: str,
    output_csv: str,
    label_file: Optional[str] = None,
    baseline_lab=BASELINE_LAB,
    extensions: tuple = (".jpg", ".jpeg", ".png", ".bmp", ".tiff"),
    debug: bool = False,
) -> pd.DataFrame:
    """
    Process all images in images_dir and save a labeled CSV to output_csv.

    Args:
        images_dir: Directory containing strip photos.
        output_csv: Output path for the CSV dataset.
        label_file: Optional labels.json; if None, parses labels from filenames.
        baseline_lab: Lab of a fresh strip for deltaE calculation.
        extensions: Accepted image file extensions.
        debug: Save debug ROI images.
    """
    images_dir = Path(images_dir)
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # Collect image files
    image_files = sorted([
        f for f in images_dir.iterdir()
        if f.suffix.lower() in extensions
    ])
    if not image_files:
        log.warning(f"No images found in {images_dir}")
        return pd.DataFrame(columns=CSV_COLUMNS)

    log.info(f"Found {len(image_files)} images in {images_dir}")

    # Load labels
    labels: Dict[str, dict] = {}
    if label_file and Path(label_file).exists():
        labels = parse_label_file(label_file)
    else:
        log.info("No label file provided — parsing labels from filenames.")

    rows = []
    skipped = []

    for img_file in tqdm(image_files, desc="Processing images"):
        fname = img_file.name

        # Get label
        label = labels.get(fname, {})
        if not label:
            label = parse_label_from_filename(fname)
        if not label:
            log.warning(f"  SKIP {fname}: no label found (add to labels.json or rename file)")
            skipped.append(fname)
            continue

        h2s_ppm = label.get("h2s_ppm", 0.0)
        exposure_min = label.get("exposure_time_min", 0.0)
        cumulative_dose = (h2s_ppm * exposure_min) / 60.0  # ppm·hr
        notes = label.get("notes", "")

        # Extract sample_id from filename
        sample_id = img_file.stem

        try:
            reading: StripReading = process_strip_image(
                str(img_file),
                baseline_lab=baseline_lab,
                debug=debug,
            )
            row = {
                "sample_id": sample_id,
                "image_path": str(img_file),
                "h2s_ppm": h2s_ppm,
                "exposure_time_min": exposure_min,
                "cumulative_dose_ppm_hr": round(cumulative_dose, 4),
                "R": round(reading.R, 3),
                "G": round(reading.G, 3),
                "B": round(reading.B, 3),
                "L": round(reading.L, 4),
                "a_star": round(reading.a, 4),
                "b_star": round(reading.b, 4),
                "delta_E": round(reading.delta_E, 4),
                "H": round(reading.H, 4),
                "S": round(reading.S, 4),
                "V": round(reading.V, 4),
                "L_corr": round(reading.L_corr, 4),
                "a_corr": round(reading.a_corr, 4),
                "b_corr": round(reading.b_corr, 4),
                "delta_E_corr": round(reading.delta_E_corr, 4),
                "confidence": round(reading.confidence, 2),
                "roi_detected": reading.roi_detected,
                "roi_method": reading.roi_method,
                "roi_confidence": round(reading.roi_confidence, 3),
                "notes": notes,
            }
            rows.append(row)
        except Exception as e:
            log.error(f"  ERROR processing {fname}: {e}")
            skipped.append(fname)

    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    df.to_csv(output_csv, index=False)

    log.info(f"\nDataset built: {len(df)} records -> {output_csv}")
    if skipped:
        log.warning(f"Skipped {len(skipped)} images: {skipped}")

    return df


def print_dataset_summary(df: pd.DataFrame):
    """Print a statistical summary of the built dataset."""
    print("\n" + "=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)
    print(f"  Total samples      : {len(df)}")
    print(f"  H2S range (ppm)    : {df['h2s_ppm'].min():.2f} - {df['h2s_ppm'].max():.2f}")
    print(f"  Dose range (ppm.hr): {df['cumulative_dose_ppm_hr'].min():.3f} - {df['cumulative_dose_ppm_hr'].max():.3f}")
    print(f"  deltaE range       : {df['delta_E'].min():.3f} - {df['delta_E'].max():.3f}")
    print(f"  Mean confidence    : {df['confidence'].mean():.2f}")
    print(f"\n  Dose distribution:")
    for _, row in df.groupby(
        pd.cut(df["cumulative_dose_ppm_hr"], bins=5)
    ).size().reset_index(name="count").iterrows():
        print(f"    {row.iloc[0]}: {row['count']} samples")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build a labeled CSV dataset from strip photos."
    )
    parser.add_argument("--images_dir", default="./sample_images",
                        help="Folder containing strip photos")
    parser.add_argument("--output", default="./datasets/dataset.csv",
                        help="Output CSV path")
    parser.add_argument("--labels", default=None,
                        help="Path to labels.json (optional; uses filename parsing if absent)")
    parser.add_argument("--baseline", default=None,
                        help="Path to a fresh strip image for baseline calibration")
    parser.add_argument("--debug", action="store_true",
                        help="Save debug ROI images")
    args = parser.parse_args()

    baseline = BASELINE_LAB
    if args.baseline:
        baseline = calibrate_baseline(args.baseline)

    df = process_image_folder(
        images_dir=args.images_dir,
        output_csv=args.output,
        label_file=args.labels,
        baseline_lab=baseline,
        debug=args.debug,
    )

    if not df.empty:
        print_dataset_summary(df)
    else:
        print("\nNo data processed. Check your images_dir and label configuration.")
