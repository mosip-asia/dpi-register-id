import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ApiError, getFaceChallenge, meanDescriptor, verifyFace, type FaceChallenge } from "../api";
import type { ScanResult } from "../face/useFaceScan";
import { useFlow } from "../flow";
import { Frame } from "../ui";

const FaceScanner = lazy(() =>
  import("../face/FaceScanner").then((mod) => ({ default: mod.FaceScanner })),
);

export function FaceCheck() {
  const navigate = useNavigate();
  const { uin, attemptsLeft, update } = useFlow();
  const [challenge, setChallenge] = useState<FaceChallenge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missingId, setMissingId] = useState(false);
  const [round, setRound] = useState(0);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    if (attemptsLeft === 0) return;
    let active = true;
    setChallenge(null);
    setError(null);
    setMissingId(false);
    getFaceChallenge("check")
      .then((next) => {
        if (active) setChallenge(next);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "The face check could not start.");
      });
    return () => {
      active = false;
    };
  }, [attemptsLeft, round]);

  async function onDone(result: ScanResult) {
    setVerifying(true);
    try {
      const verdict = await verifyFace({
        uin: uin ?? "",
        probeDescriptor: meanDescriptor(result.descriptors),
        liveness: {
          challengeId: result.challengeId,
          engine: result.engine,
          blinkCount: result.blinkCount,
          sweepYaws: result.sweepYaws,
        },
      });
      if (verdict.isFaceMatch) {
        update({
          verified: true,
          lastDistance: verdict.euclideanDistance,
          lastMessage: verdict.message,
        });
        navigate({ to: "/prove/verified" });
        return;
      }
      if (verdict.compared) {
        update({
          verified: false,
          lastDistance: verdict.euclideanDistance,
          lastMessage: verdict.message,
          attemptsLeft: Math.max(0, attemptsLeft - 1),
        });
        navigate({ to: "/prove/unmatched" });
        return;
      }
      update({ verified: false, lastMessage: verdict.message });
      setVerifying(false);
      setError(verdict.message ?? "The server did not compare this scan.");
    } catch (caught) {
      setVerifying(false);
      if (caught instanceof ApiError && caught.status === 404) {
        setMissingId(true);
        setError("No ID with that number.");
        return;
      }
      setError(caught instanceof Error ? caught.message : "The face check could not be sent.");
    }
  }

  return (
    <Frame
      stepIndex={3}
      stepCount={4}
      kicker="Face check"
      title="Confirm it is you"
      aside={<p>The server compares this scan with the face stored for the ID. The head turn is checked in this browser.</p>}
    >
      {attemptsLeft === 0 ? (
        <div className="stack">
          <p className="callout" role="status">
            No attempts left. An officer can review the application.
          </p>
          <div className="actions">
            <Link to="/enroll/help" className="secondary">
              Get help
            </Link>
          </div>
        </div>
      ) : (
        <>
          {error ? (
            <p className="note" role="alert">
              {error}
            </p>
          ) : null}
          {missingId ? (
            <div className="actions">
              <Link to="/prove/id" className="primary">
                Enter the ID again
              </Link>
            </div>
          ) : error ? (
            <div className="actions">
              <button type="button" className="primary" onClick={() => setRound((current) => current + 1)}>
                Scan again
              </button>
            </div>
          ) : verifying ? (
            <p className="status" role="status" aria-busy="true">
              Confirming with the server…
            </p>
          ) : challenge ? (
            <Suspense fallback={<p className="status" role="status">Getting the face check ready…</p>}>
              <FaceScanner
                key={challenge.challengeId}
                mode="check"
                challengeId={challenge.challengeId}
                requiredBlinks={challenge.requiredBlinks}
                onDone={(result) => void onDone(result)}
              />
            </Suspense>
          ) : (
            <p className="status" role="status">Getting the face check ready…</p>
          )}
        </>
      )}
    </Frame>
  );
}
