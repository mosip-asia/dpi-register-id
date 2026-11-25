import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { CircleHelp } from "lucide-react";
import { getFaceChallenge, reportAttempt, type FaceChallenge } from "../api";
import type { ScanResult } from "../face/useFaceScan";
import { useFlow } from "../flow";
import { enrollStepCount, Frame } from "../ui";

const FaceScanner = lazy(() =>
  import("../face/FaceScanner").then((mod) => ({ default: mod.FaceScanner })),
);

export function Capture() {
  const navigate = useNavigate();
  const { update } = useFlow();
  const [challenge, setChallenge] = useState<FaceChallenge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const reportedChallenge = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    setChallenge(null);
    setError(null);
    getFaceChallenge("enroll")
      .then((next) => {
        if (active) setChallenge(next);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : "The face check could not start.");
        if (reportedChallenge.current === round) return;
        reportedChallenge.current = round;
        reportAttempt({ kind: "enroll", reasonCode: "enroll_failed", detail: "challenge" });
      });
    return () => {
      active = false;
    };
  }, [round]);

  function onDone(result: ScanResult) {
    update({
      photoDataUrl: result.photoDataUrl,
      scan: {
        descriptors: result.descriptors,
        blinkCount: result.blinkCount,
        sweepYaws: result.sweepYaws,
        challengeId: result.challengeId,
      },
    });
    navigate({ to: "/enroll/review" });
  }

  return (
    <Frame
      stepIndex={7}
      stepCount={enrollStepCount}
      kicker="Photo"
      title="Scan your face"
      aside={
        <>
          <p>This browser checks a slow head turn from left to right. The server stores the photo and the face signature.</p>
          <span className="inline-icon">
            <CircleHelp size={20} strokeWidth={1.75} aria-hidden />
            <Link to="/enroll/help">Need help?</Link>
          </span>
        </>
      }
    >
      {error ? (
        <>
          <p className="note" role="alert">
            {error}
          </p>
          <div className="actions">
            <button type="button" className="primary" onClick={() => setRound((current) => current + 1)}>
              Try again
            </button>
          </div>
        </>
      ) : challenge ? (
        <Suspense fallback={<p className="status" role="status">Getting the face check ready…</p>}>
          <FaceScanner
            key={challenge.challengeId}
            mode="enroll"
            challengeId={challenge.challengeId}
            requiredBlinks={challenge.requiredBlinks}
            onDone={onDone}
          />
        </Suspense>
      ) : (
        <p className="status" role="status">Getting the face check ready…</p>
      )}
    </Frame>
  );
}
