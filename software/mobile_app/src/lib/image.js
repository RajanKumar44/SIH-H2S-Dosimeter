/**
 * image.js — client-side capture validation + preprocessing.
 *
 * Runs BEFORE the upload so an obviously unusable frame is rejected on the
 * phone instead of burning a round trip. The authoritative validation still
 * happens server-side in `ml_inference.analyze_strip_image` (which also
 * downscales); this is a fast, friendly pre-filter that mirrors those limits.
 */

export const MAX_UPLOAD_BYTES = 12 * 1024 * 1024; // matches ml_inference.MAX_IMAGE_BYTES
export const MAX_EDGE = 1600; // matches ml_inference.MAX_ANALYSIS_EDGE
export const MIN_EDGE = 64; // server rejects < 16px; be stricter for real photos
export const ACCEPTED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"];

/** A pre-flight rejection with an actionable message for the operator. */
export class ImageRejected extends Error {
  constructor(message, hint) {
    super(message);
    this.name = "ImageRejected";
    this.hint = hint || "";
  }
}

export function isAcceptedType(type) {
  const t = String(type || "").toLowerCase().split(";")[0].trim();
  if (!t) return true; // some Android pickers omit the type; let decoding decide
  return ACCEPTED_TYPES.includes(t) || t === "application/octet-stream";
}

/** Load a Blob into an HTMLImageElement (rejects if undecodable). */
export function loadImage(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(
        new ImageRejected(
          "That file could not be read as an image.",
          "Use a JPEG or PNG photo taken with the camera.",
        ),
      );
    };
    img.src = url;
  });
}

/**
 * Quality metrics over a downscaled copy of the frame.
 * Cheap, dependency-free proxies for the two failure modes we see in the
 * field: a dark/blown-out frame, and a frame pointed at nothing (flat wall).
 *
 * @returns {{brightness:number, contrast:number, saturation:number, clippedPct:number}}
 */
export function frameMetrics(imageData) {
  const { data } = imageData;
  const n = data.length / 4;
  let sum = 0;
  let sumSq = 0;
  let satSum = 0;
  let clipped = 0;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const lum = 0.299 * r + 0.587 * g + 0.114 * b;
    sum += lum;
    sumSq += lum * lum;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    satSum += max === 0 ? 0 : (max - min) / max;
    if (lum <= 4 || lum >= 251) clipped += 1;
  }

  const mean = sum / n;
  const variance = Math.max(0, sumSq / n - mean * mean);
  return {
    brightness: mean / 255,
    contrast: Math.sqrt(variance) / 255,
    saturation: satSum / n,
    clippedPct: clipped / n,
  };
}

const ANALYSIS_SAMPLE_EDGE = 128;

function drawToCanvas(img, width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return { canvas, ctx };
}

/** Canvas → JPEG Blob (Safari-safe promise wrapper). */
function canvasToJpeg(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve(blob)
          : reject(new ImageRejected("Could not encode the captured photo.")),
      "image/jpeg",
      quality,
    );
  });
}

/**
 * Validate + normalise a captured/selected image for upload.
 *
 * - rejects non-images, oversized files and frames too small to analyse
 * - warns (does not block) on dark / washed-out / featureless frames so the
 *   operator can retake before spending a scan
 * - downscales to MAX_EDGE and re-encodes as JPEG q0.9 → typically < 400 KB,
 *   which keeps the upload fast on a mine-site connection
 *
 * @param {File|Blob} input
 * @returns {Promise<{file: File, previewUrl: string, width:number, height:number,
 *                    warnings: string[], metrics: object, originalBytes: number}>}
 */
export async function prepareImage(input) {
  if (!input) throw new ImageRejected("No image was selected.");
  if (!isAcceptedType(input.type)) {
    throw new ImageRejected(
      `Unsupported file type "${input.type}".`,
      "Capture a JPEG or PNG photo of the strip.",
    );
  }
  if (input.size > MAX_UPLOAD_BYTES) {
    throw new ImageRejected(
      `That image is ${(input.size / 1e6).toFixed(1)} MB — the limit is ` +
        `${MAX_UPLOAD_BYTES / (1024 * 1024)} MB.`,
      "Retake it at a lower resolution.",
    );
  }

  const img = await loadImage(input);
  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;

  if (!w || !h) {
    throw new ImageRejected("The image has no readable dimensions.");
  }
  if (Math.min(w, h) < MIN_EDGE) {
    throw new ImageRejected(
      `That image is only ${w}\u00D7${h} px — too small to analyse.`,
      "Move closer to the strip and retake the photo.",
    );
  }

  // ── Quality pre-check on a tiny sample ────────────────────────────────
  const sampleScale = Math.min(1, ANALYSIS_SAMPLE_EDGE / Math.max(w, h));
  const sample = drawToCanvas(img, w * sampleScale, h * sampleScale);
  const metrics = frameMetrics(
    sample.ctx.getImageData(0, 0, sample.canvas.width, sample.canvas.height),
  );

  const warnings = [];
  if (metrics.brightness < 0.16)
    warnings.push("The photo looks very dark — add light or use the flash.");
  else if (metrics.brightness > 0.9)
    warnings.push("The photo looks over-exposed — move out of direct glare.");
  if (metrics.clippedPct > 0.35)
    warnings.push("Large areas are pure black or pure white — reframe the strip.");
  if (metrics.contrast < 0.035)
    warnings.push(
      "The frame is almost featureless — make sure the strip fills the guide box.",
    );

  // ── Downscale + re-encode ─────────────────────────────────────────────
  const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
  const outW = Math.round(w * scale);
  const outH = Math.round(h * scale);
  const { canvas } = drawToCanvas(img, outW, outH);
  const blob = await canvasToJpeg(canvas, 0.9);

  const file = new File([blob], `strip_${Date.now()}.jpg`, { type: "image/jpeg" });

  return {
    file,
    previewUrl: URL.createObjectURL(blob),
    width: outW,
    height: outH,
    warnings,
    metrics,
    originalBytes: input.size,
  };
}
