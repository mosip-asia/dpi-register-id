import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useState } from "react";
import { ApiError, enrollCitizen, FACE_ENGINE, issueUin } from "../api";
import { useFlow } from "../flow";
import { Frame } from "../ui";

function firstName(fullName: string) {
  return fullName.trim().split(/\s+/)[0] ?? "";
}

function needsRescan(message: string) {
  return /challenge|scan|same face|blink|head turn|descriptor/i.test(message);
}

export function Ready() {
  const flow = useFlow();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const given = firstName(flow.fullName);
  const title = flow.enrolled
    ? given
      ? `${given}, your ID is ready`
      : "Your ID is ready"
    : "Create your ID";

  async function createId() {
    if (!flow.photoDataUrl || !flow.scan || !flow.fullName.trim() || !flow.email.trim()) {
      setError("Go back and scan your face again. A name, an email, and a scan are required.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const uin = flow.uin ?? (await issueUin());
      const result = await enrollCitizen({
        uin,
        fullName: flow.fullName,
        email: flow.email,
        faceImage: flow.photoDataUrl,
        faceDescriptors: flow.scan.descriptors,
        liveness: {
          challengeId: flow.scan.challengeId,
          engine: FACE_ENGINE,
          blinkCount: flow.scan.blinkCount,
          sweepYaws: flow.scan.sweepYaws,
        },
      });
      flow.update({
        uin: result.uin,
        enrolled: true,
        recordStatus: result.recordStatus,
        lastMessage: result.message,
        photoDataUrl: null,
        scan: null,
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : "Enrollment failed.");
    } finally {
      setPending(false);
    }
  }

  const rescan = error !== null && needsRescan(error);

  return (
    <Frame
      stepIndex={6}
      stepCount={6}
      kicker="Ready"
      title={title}
      aside={
        <p>
          This screen does not send email. The head turn was checked in this browser, not on the server.
        </p>
      }
    >
      <div className="stack">
        {flow.enrolled && flow.uin ? (
          <div className="success">
            <p className="inline-icon">
              <Check size={20} strokeWidth={1.75} aria-hidden />
              Your registration number
            </p>
            <p className="uin">{flow.uin}</p>
            <p>Your face is enrolled. The server compares a new scan with it when you use this ID.</p>
          </div>
        ) : (
          <p>This creates the registration number and stores your photo and face signature.</p>
        )}
        {error ? <p className="note">{error}</p> : null}
      </div>
      <div className="actions">
        {flow.enrolled && flow.uin ? (
          <>
            <Link to="/id" className="primary">
              My ID
            </Link>
            <Link to="/prove" className="secondary">
              Use this ID
            </Link>
          </>
        ) : rescan ? (
          <Link to="/enroll/capture" className="primary">
            Scan again
          </Link>
        ) : (
          <button type="button" className="primary" disabled={pending} onClick={() => void createId()}>
            {pending ? "Creating…" : "Create my ID"}
          </button>
        )}
        {flow.enrolled ? null : (
          <Link to="/enroll/review" className="quiet">
            Back to review
          </Link>
        )}
      </div>
    </Frame>
  );
}
