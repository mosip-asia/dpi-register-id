import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  FACE_ENGINE,
  analyze,
  descriptorDistance,
  loadFaceModels,
  ovalGeometry,
  type FaceSample,
} from "./engine";
import { createBlinkTracker, createSweepTracker, validateSweep, type Sector } from "./liveness";

export type ScanMode = "enroll" | "check";

export type ScanPhase =
  | "loading"
  | "camera"
  | "position"
  | "blink"
  | "sweep"
  | "frontal"
  | "capture"
  | "done"
  | "error";

export type ScanError =
  | "models"
  | "camera-blocked"
  | "camera-missing"
  | "camera-busy"
  | "camera-insecure"
  | "camera";

export type ScanWarning = "many" | "no-face" | null;

export interface ScanResult {
  engine: typeof FACE_ENGINE;
  challengeId: string;
  descriptors: number[][];
  blinkCount: number;
  sweepYaws: number[];
  photoDataUrl: string;
}

export interface FaceScanOptions {
  mode: ScanMode;
  challengeId: string;
  requiredBlinks: number;
  onDone(result: ScanResult): void;
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
}

export interface FaceScanState {
  phase: ScanPhase;
  error: ScanError | null;
  warning: ScanWarning;
  blinkCount: number;
  visited: Sector[];
  captured: number;
  captureTarget: number;
  /** Raw camera frame width over height, once known. */
  frameRatio: number | null;
}

const HOLD_MS = 500;
const NO_FACE_MS = 8000;
const FRONTAL_YAW = 0.12;
const CAPTURE_YAW = 0.16;
const CAPTURE_GAP_MS = 300;
const FRONTAL_STREAK = 2;
const MAX_PAIR_DISTANCE = 0.6;
const DESCRIPTOR_LENGTH = 128;

const captureTargetFor = (mode: ScanMode) => (mode === "enroll" ? 3 : 2);

function initialState(mode: ScanMode): FaceScanState {
  return {
    phase: "loading",
    error: null,
    warning: null,
    blinkCount: 0,
    visited: [],
    captured: 0,
    captureTarget: captureTargetFor(mode),
    frameRatio: null,
  };
}

function cameraError(err: unknown): ScanError {
  const name = err instanceof DOMException || err instanceof Error ? err.name : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return "camera-blocked";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") {
    return "camera-missing";
  }
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "camera-busy";
  return "camera";
}

function whenMetadata(video: HTMLVideoElement): Promise<void> {
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA && video.videoWidth > 0) return Promise.resolve();
  return new Promise((resolve) => video.addEventListener("loadedmetadata", () => resolve(), { once: true }));
}

function descriptorsAgree(descriptors: number[][]): boolean {
  for (let i = 0; i < descriptors.length; i++) {
    for (let j = i + 1; j < descriptors.length; j++) {
      if (descriptorDistance(descriptors[i], descriptors[j]) >= MAX_PAIR_DISTANCE) return false;
    }
  }
  return true;
}

function cssColor(el: Element, name: string, fallback: string): string {
  return getComputedStyle(el).getPropertyValue(name).trim() || fallback;
}

function drawGuide(canvas: HTMLCanvasElement, sample: FaceSample | null) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  const { cx, cy, rx, ry } = ovalGeometry(width, height);
  if (!(rx > 0) || !(ry > 0)) return;
  const accepted = sample?.status === "one" && sample.centered && sample.sizeOk;
  const line = Math.max(2, Math.round(Math.min(width, height) / 160));

  ctx.save();
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  if (accepted) {
    ctx.lineWidth = line * 2.5;
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    ctx.lineWidth = line * 1.5;
    ctx.strokeStyle = cssColor(canvas, "--ait-green", "#3f6433");
  } else {
    ctx.setLineDash([line * 4, line * 3]);
    ctx.lineWidth = line;
    ctx.strokeStyle = "#ffffff";
  }
  ctx.stroke();
  ctx.restore();
}

/** Camera, model loading, detection loop and guided liveness phases for FaceScanner. */
export function useFaceScan({
  mode,
  challengeId,
  requiredBlinks,
  onDone,
  videoRef,
  canvasRef,
}: FaceScanOptions): FaceScanState & { retry(): void } {
  const [state, setState] = useState<FaceScanState>(() => initialState(mode));
  const [attempt, setAttempt] = useState(0);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    let finished = false;
    let stream: MediaStream | null = null;
    let raf = 0;
    const captureTarget = captureTargetFor(mode);
    const blink = createBlinkTracker();
    const sweep = createSweepTracker();
    const snapshot = document.createElement("canvas");

    let phase: ScanPhase = "loading";
    let heldSince = 0;
    let lastFaceAt = 0;
    let frontalStreak = 0;
    let lastCaptureAt = 0;
    let descriptors: number[][] = [];
    let photo = { url: "", yaw: Number.POSITIVE_INFINITY };

    let shown = initialState(mode);
    const patch = (next: Partial<FaceScanState>) => {
      const keys = Object.keys(next) as Array<keyof FaceScanState>;
      if (!keys.some((key) => shown[key] !== next[key])) return;
      shown = { ...shown, ...next };
      setState(shown);
    };

    const goTo = (next: ScanPhase) => {
      phase = next;
      heldSince = 0;
      frontalStreak = 0;
      patch({ phase: next });
    };

    const fail = (error: ScanError) => {
      finished = true;
      stopCamera();
      phase = "error";
      patch({ phase: "error", error });
    };

    function stopCamera() {
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      const video = videoRef.current;
      if (video) video.srcObject = null;
    }

    function syncFrame(video: HTMLVideoElement) {
      const canvas = canvasRef.current;
      const { videoWidth: w, videoHeight: h } = video;
      if (canvas && (canvas.width !== w || canvas.height !== h)) {
        canvas.width = w;
        canvas.height = h;
      }
      if (w && h) patch({ frameRatio: w / h });
    }

    function noteFaces(sample: FaceSample, now: number) {
      if (sample.status === "none") {
        if (now - lastFaceAt > NO_FACE_MS) patch({ warning: "no-face" });
        return;
      }
      lastFaceAt = now;
      patch({ warning: sample.status === "many" ? "many" : null });
    }

    async function track(video: HTMLVideoElement) {
      const sample = await analyze(video);
      if (cancelled) return;
      const now = performance.now();
      if (canvasRef.current) drawGuide(canvasRef.current, sample);
      noteFaces(sample, now);

      if (sample.status !== "one") {
        blink.interrupt();
        sweep.interrupt();
        heldSince = 0;
        frontalStreak = 0;
        return;
      }

      const inOval = sample.centered && sample.sizeOk;
      if (phase !== "position" && sample.eyes && blink.update(sample.eyes, now).blinked) {
        patch({ blinkCount: blink.count });
      }

      switch (phase) {
        case "position":
          if (!inOval) heldSince = 0;
          else if (!heldSince) heldSince = now;
          else if (now - heldSince >= HOLD_MS) goTo(requiredBlinks > 0 ? "blink" : "sweep");
          break;
        case "blink":
          if (requiredBlinks <= 0 || blink.count >= requiredBlinks) goTo("sweep");
          break;
        case "sweep":
          if (!inOval || sample.yaw === null) {
            sweep.interrupt();
            break;
          }
          if (sweep.update(sample.yaw)) patch({ visited: sweep.visited() });
          if (sweep.complete) {
            const yaws = sweep.sweepYaws();
            if (yaws && validateSweep(yaws)) goTo("frontal");
            else {
              sweep.reset();
              patch({ visited: [] });
            }
          }
          break;
        case "frontal": {
          const frontal = inOval && sample.eyesUsable && sample.yaw !== null && Math.abs(sample.yaw) < FRONTAL_YAW;
          frontalStreak = frontal ? frontalStreak + 1 : 0;
          if (frontalStreak >= FRONTAL_STREAK) goTo("capture");
          break;
        }
        default:
          break;
      }
    }

    async function capture(video: HTMLVideoElement) {
      if (performance.now() - lastCaptureAt < CAPTURE_GAP_MS) return;
      const { videoWidth: w, videoHeight: h } = video;
      if (!w || !h) return;
      snapshot.width = w;
      snapshot.height = h;
      const ctx = snapshot.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, w, h);

      const sample = await analyze(snapshot, { withDescriptor: true });
      if (cancelled) return;
      const now = performance.now();
      if (canvasRef.current) drawGuide(canvasRef.current, sample);
      noteFaces(sample, now);

      const usable =
        sample.status === "one" &&
        sample.centered &&
        sample.sizeOk &&
        sample.eyesUsable &&
        sample.yaw !== null &&
        Math.abs(sample.yaw) < CAPTURE_YAW &&
        sample.descriptor?.length === DESCRIPTOR_LENGTH;
      if (!usable || !sample.descriptor || sample.yaw === null) return;

      lastCaptureAt = now;
      descriptors.push(sample.descriptor);
      if (Math.abs(sample.yaw) < photo.yaw) {
        photo = { url: snapshot.toDataURL("image/jpeg", 0.85), yaw: Math.abs(sample.yaw) };
      }
      patch({ captured: descriptors.length });
      if (descriptors.length < captureTarget) return;

      if (!descriptorsAgree(descriptors)) {
        descriptors = [];
        photo = { url: "", yaw: Number.POSITIVE_INFINITY };
        patch({ captured: 0 });
        return;
      }

      const sweepYaws = sweep.sweepYaws();
      if (!sweepYaws) return;
      finished = true;
      stopCamera();
      goTo("done");
      onDoneRef.current({
        engine: FACE_ENGINE,
        challengeId,
        descriptors,
        blinkCount: blink.count,
        sweepYaws,
        photoDataUrl: photo.url,
      });
    }

    const loop = async () => {
      if (cancelled || finished) return;
      const video = videoRef.current;
      if (video && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        syncFrame(video);
        try {
          if (phase === "capture") await capture(video);
          else await track(video);
        } catch (err) {
          console.warn("Face detection failed", err);
        }
      }
      if (!cancelled && !finished) raf = requestAnimationFrame(loop);
    };

    setState(shown);

    void (async () => {
      try {
        await loadFaceModels();
      } catch (err) {
        console.warn(err);
        if (!cancelled) fail("models");
        return;
      }
      if (cancelled) return;
      goTo("camera");

      if (!navigator.mediaDevices?.getUserMedia) {
        fail("camera-insecure");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        });
      } catch (err) {
        if (!cancelled) fail(cameraError(err));
        return;
      }
      const video = videoRef.current;
      if (cancelled || !video) {
        stopCamera();
        return;
      }

      video.srcObject = stream;
      await whenMetadata(video);
      if (cancelled) return;
      try {
        await video.play();
      } catch {
        // autoplay of a muted inline video normally succeeds; the loop waits for frames either way
      }
      if (cancelled) return;
      syncFrame(video);
      lastFaceAt = performance.now();
      goTo("position");
      raf = requestAnimationFrame(loop);
    })();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      stopCamera();
    };
  }, [mode, challengeId, requiredBlinks, attempt, videoRef, canvasRef]);

  return { ...state, retry };
}
