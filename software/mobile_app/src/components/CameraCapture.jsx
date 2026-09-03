import { useCallback, useEffect, useRef, useState } from "react";
import { ImageRejected, prepareImage } from "../lib/image";

/**
 * CameraCapture — live rear-camera preview with a gallery/file fallback.
 *
 * Two independent capture paths, because neither works everywhere:
 *
 *  1. getUserMedia live preview + <canvas> grab. Needs a secure context
 *     (https:// or localhost). Gives the framing guide, which matters for a
 *     colorimetric read.
 *  2. <input type="file" accept="image/*" capture="environment"> — opens the
 *     native camera app on Android/iOS and works on plain http:// too. This is
 *     always offered, so the demo cannot be blocked by a permission prompt.
 *
 * Whichever path produced the frame, the bytes go through `prepareImage`
 * (validation + downscale) before they reach the API.
 */

function cameraErrorMessage(err) {
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Camera permission was denied. Allow camera access, or use \u201CChoose photo\u201D below.";
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return "No usable camera was found on this device. Use \u201CChoose photo\u201D below.";
  if (name === "NotReadableError")
    return "The camera is busy in another app. Close it and try again.";
  return "The live camera could not be started. Use \u201CChoose photo\u201D below.";
}

export default function CameraCapture({ onImage, disabled }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const fileRef = useRef(null);

  const [live, setLive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [camError, setCamError] = useState("");
  const [busy, setBusy] = useState(false);

  const secure =
    typeof window !== "undefined" &&
    (window.isSecureContext ||
      ["localhost", "127.0.0.1"].includes(window.location.hostname));
  const supported =
    typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setLive(false);
  }, []);

  useEffect(() => stop, [stop]);

  const start = useCallback(async () => {
    setCamError("");
    if (!supported) {
      setCamError("This browser does not expose a camera API. Use \u201CChoose photo\u201D below.");
      return;
    }
    if (!secure) {
      setCamError(
        "Live camera needs HTTPS (or localhost). Use \u201CChoose photo\u201D \u2014 it opens the phone camera app.",
      );
      return;
    }
    setStarting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setLive(true);
    } catch (err) {
      setCamError(cameraErrorMessage(err));
      stop();
    } finally {
      setStarting(false);
    }
  }, [secure, stop, supported]);

  const handlePrepared = useCallback(
    async (blob) => {
      setBusy(true);
      try {
        const prepared = await prepareImage(blob);
        setCamError("");
        onImage(prepared);
        stop();
      } catch (err) {
        setCamError(
          err instanceof ImageRejected
            ? `${err.message}${err.hint ? ` ${err.hint}` : ""}`
            : "That image could not be processed. Try again.",
        );
      } finally {
        setBusy(false);
      }
    },
    [onImage, stop],
  );

  const shoot = useCallback(async () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      setCamError("The camera is still warming up — try again in a moment.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.92));
    if (!blob) {
      setCamError("Could not grab a frame from the camera. Try again.");
      return;
    }
    await handlePrepared(blob);
  }, [handlePrepared]);

  const onPick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (f) await handlePrepared(f);
  };

  return (
    <div className="capture">
      <div className={`viewfinder ${live ? "is-live" : ""}`}>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video ref={videoRef} playsInline muted autoPlay className="viewfinder-video" />
        {live ? (
          <div className="viewfinder-guide" aria-hidden="true">
            <span className="guide-hint">Fill this box with the strip</span>
          </div>
        ) : (
          <div className="viewfinder-idle">
            <span className="viewfinder-icon" aria-hidden="true">
              {"\uD83D\uDCF7"}
            </span>
            <p className="viewfinder-title">Scan the dosimeter strip</p>
            <p className="viewfinder-sub">
              Hold the wristband flat, 15–20 cm away, in even light. Include the
              printed reference card if the band has one.
            </p>
          </div>
        )}
        {busy && (
          <div className="viewfinder-busy" role="status">
            <span className="spinner" aria-hidden="true" />
            <span>Checking photo…</span>
          </div>
        )}
      </div>

      {camError && (
        <p className="inline-warn" role="alert">
          {camError}
        </p>
      )}

      <div className="capture-actions">
        {live ? (
          <>
            <button
              type="button"
              className="btn btn-primary btn-lg"
              onClick={shoot}
              disabled={disabled || busy}
            >
              Capture strip
            </button>
            <button type="button" className="btn btn-ghost" onClick={stop} disabled={busy}>
              Stop camera
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="btn btn-primary btn-lg"
              onClick={start}
              disabled={disabled || busy || starting}
            >
              {starting ? "Starting camera…" : "Open camera"}
            </button>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => fileRef.current?.click()}
              disabled={disabled || busy}
            >
              Choose photo
            </button>
          </>
        )}
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={onPick}
        hidden
      />
    </div>
  );
}
