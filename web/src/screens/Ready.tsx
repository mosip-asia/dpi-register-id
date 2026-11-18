import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useState } from "react";
import { ApiError, enrollCitizen, FACE_ENGINE, issueUin } from "../api";
import { drawIdCard } from "../drawIdCard";
import { IdCard } from "../IdCard";
import { useFlow } from "../flow";
import { CopyValue, Frame } from "../ui";

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
  const [emailIdCard, setEmailIdCard] = useState(false);
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
      // A number typed earlier on the prove screen is not an issued registration number.
      const uin = await issueUin();
      let idCardImage: string | undefined;
      if (emailIdCard) {
        try {
          const drawn = await drawIdCard({
            uin,
            fullName: flow.fullName,
            dateOfBirth: flow.dateOfBirth,
          });
          if (drawn) idCardImage = drawn;
        } catch {
          idCardImage = undefined;
        }
      }
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
        emailIdCard,
        idCardImage,
      });
      flow.update({
        uin: result.uin,
        enrolled: true,
        emailSent: result.emailSent,
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
      stepIndex={8}
      stepCount={8}
      kicker="Ready"
      title={title}
      aside={
        <p>
          {flow.enrolled
            ? emailIdCard
              ? flow.emailSent
                ? `The ID card was emailed to ${flow.email}.`
                : "The ID card was not emailed. Save it on this page."
              : flow.emailSent
                ? `A copy of this number was emailed to ${flow.email}.`
                : "No confirmation email was sent. Keep this number."
            : `If email delivery is available, the email includes a QR code of the registration number. Tick the box to also email the ID card to ${flow.email}.`}{" "}
          The head turn was checked in this browser, not on the server.
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
            <div className="uin-row">
              <p className="uin">{flow.uin}</p>
              <CopyValue value={flow.uin} />
            </div>
            <IdCard uin={flow.uin} fullName={flow.fullName} dateOfBirth={flow.dateOfBirth} />
            <p>Your face is enrolled. The server compares a new scan with it when you use this ID.</p>
          </div>
        ) : (
          <p>This creates the registration number and stores your photo and face signature.</p>
        )}
        {error ? (
          <p className="note" role="alert">
            {error}
          </p>
        ) : null}
      </div>
      {!flow.enrolled && !rescan ? (
        <label className="check">
          <input
            type="checkbox"
            checked={emailIdCard}
            disabled={pending}
            onChange={(event) => setEmailIdCard(event.target.checked)}
          />
          Email the ID card to {flow.email}
        </label>
      ) : null}
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
          <button type="button" className="primary" disabled={pending} aria-busy={pending} onClick={() => void createId()}>
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
