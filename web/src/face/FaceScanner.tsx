import { useEffect, useRef, type CSSProperties } from "react";
import { Check } from "lucide-react";
import { reportAttempt } from "../api";
import { SECTORS, SECTOR_LABELS } from "./liveness";
import { useFaceScan, type ScanError, type ScanMode, type ScanPhase, type ScanResult } from "./useFaceScan";

export type { ScanResult } from "./useFaceScan";

export interface FaceScannerProps {
  mode: ScanMode;
  challengeId: string;
  requiredBlinks: number;
  onDone(result: ScanResult): void;
}

const INSTRUCTIONS: Record<ScanPhase, string> = {
  loading: "Getting the face check ready…",
  camera: "Starting the camera…",
  position: "Put your face in the oval",
  blink: "Blink",
  sweep: "Turn your head slowly to your left, then to your right",
  frontal: "Look at the camera",
  capture: "Hold still",
  done: "Done",
  error: "",
};

const ERRORS: Record<ScanError, string> = {
  models: "The face check could not load. Check your internet connection and try again.",
  "camera-blocked": "The camera is blocked. Allow it in the address bar, then try again.",
  "camera-missing": "No camera was found. Connect a camera and try again.",
  "camera-busy": "Another app is using the camera. Close it and try again.",
  "camera-insecure": "This page cannot use the camera. Open it with https:// and try again.",
  camera: "The camera could not start. Try again.",
};

const WARNINGS = {
  many: "Only one person should be in view.",
  "no-face": "We cannot see your face. Face a light and sit about an arm's length from the camera.",
};

const SWEEP_PHASES: ReadonlySet<ScanPhase> = new Set(["sweep", "frontal", "capture", "done"]);

export function FaceScanner({ mode, challengeId, requiredBlinks, onDone }: FaceScannerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const reportedCamera = useRef<ScanError | null>(null);
  const scan = useFaceScan({ mode, challengeId, requiredBlinks, onDone, videoRef, canvasRef });

  useEffect(() => {
    if (mode !== "enroll") return;
    if (!scan.error) {
      reportedCamera.current = null;
      return;
    }
    if (scan.error === "models") return;
    if (reportedCamera.current === scan.error) return;
    reportedCamera.current = scan.error;
    reportAttempt({ kind: "camera", reasonCode: "camera_unavailable", detail: scan.error });
  }, [mode, scan.error]);

  const live = scan.phase !== "loading" && scan.phase !== "camera" && scan.phase !== "error";
  const veil = scan.phase === "error" ? "" : live && scan.phase !== "done" ? null : INSTRUCTIONS[scan.phase];
  const stageStyle = scan.frameRatio ? ({ "--face-ratio": scan.frameRatio } as CSSProperties) : undefined;

  return (
    <div className="face-scanner">
      <div className="stage face-stage" style={stageStyle}>
        <video className="video face-video" autoPlay playsInline muted ref={videoRef} />
        <canvas className="face-overlay" ref={canvasRef} aria-hidden="true" />
        {veil !== null && (
          <div className="face-veil" aria-hidden="true">
            {veil}
          </div>
        )}
      </div>

      <div className="face-status" aria-live="polite">
        {scan.error ? (
          <p className="note" role="alert">
            {ERRORS[scan.error]}
          </p>
        ) : (
          <>
            <p className="face-instruction">{INSTRUCTIONS[scan.phase]}</p>
            {scan.phase === "blink" && requiredBlinks > 1 && (
              <p className="face-meter">
                Blinks {Math.min(scan.blinkCount, requiredBlinks)} of {requiredBlinks}
              </p>
            )}
            {scan.phase === "capture" && (
              <p className="face-meter">
                Photo {scan.captured} of {scan.captureTarget}
              </p>
            )}
            {scan.warning && live && scan.phase !== "done" && <p className="face-hint">{WARNINGS[scan.warning]}</p>}
          </>
        )}
      </div>

      {SWEEP_PHASES.has(scan.phase) && (
        <ol className="face-sectors" aria-label="Head turn">
          {SECTORS.map((sector) => {
            const done = scan.visited.includes(sector);
            return (
              <li key={sector} className={done ? "face-sector is-done" : "face-sector"}>
                {done && <Check size={14} strokeWidth={3} aria-hidden="true" />}
                <span>{SECTOR_LABELS[sector]}</span>
                <span className="visually-hidden">{done ? ", done" : ", not yet"}</span>
              </li>
            );
          })}
        </ol>
      )}

      {scan.error && (
        <div className="actions">
          <button type="button" className="primary" onClick={scan.retry}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
