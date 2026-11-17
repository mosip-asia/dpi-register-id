import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useState } from "react";
import { enrollCitizen, issueUin } from "../api";
import { useFlow } from "../flow";
import { Frame } from "../ui";

function firstName(fullName: string) {
  return fullName.trim().split(/\s+/)[0] ?? "";
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
    if (!flow.photoDataUrl || !flow.fullName.trim() || !flow.email.trim()) {
      setError("Go back to review. A name, an email, and a photo are required.");
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
      });
      flow.update({
        uin: result.uin,
        enrolled: true,
        lastMessage: "Draft stored. The face was not matched.",
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Enrollment failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <Frame
      stepIndex={6}
      stepCount={6}
      kicker="Ready"
      title={title}
      aside={<p>This screen does not send email, and it does not mean the face matched.</p>}
    >
      <div className="stack">
        {flow.enrolled && flow.uin ? (
          <div className="success">
            <p className="inline-icon">
              <Check size={20} strokeWidth={1.75} aria-hidden />
              Your registration number
            </p>
            <p className="uin">{flow.uin}</p>
          </div>
        ) : (
          <p>This creates the registration number and stores the photo as a draft.</p>
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
        ) : (
          <button type="button" className="primary" disabled={pending} onClick={() => void createId()}>
            {pending ? "Creating…" : "Create my ID"}
          </button>
        )}
        <Link to="/enroll/review" className="quiet">
          Back to review
        </Link>
      </div>
    </Frame>
  );
}
