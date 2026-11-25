import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { citizenFields, displayValue, fieldMeta, identityReady } from "../identityFields";
import { enrollStepCount, Frame } from "../ui";

export function Review() {
  const flow = useFlow();
  const scanned = Boolean(flow.photoDataUrl && flow.scan);
  const canCreate = scanned && identityReady(flow);

  return (
    <Frame
      stepIndex={8}
      stepCount={enrollStepCount}
      kicker="Review"
      title="Check before we create your ID"
    >
      <div className="stack">
        {flow.photoDataUrl ? (
          <img alt="Preview of the photo that will be stored with your ID" src={flow.photoDataUrl} className="photo" />
        ) : (
          <div className="panel">
            <p>No photo yet.</p>
          </div>
        )}
        <p>
          {scanned
            ? "Face scan done: the head turn was checked in this browser."
            : "No face scan yet."}
        </p>
        <div className="facts">
          {citizenFields.map((field) => (
            <p key={field}>
              <strong>{fieldMeta[field].label}</strong>
              <span>{displayValue(field, flow[field])}</span>
              <Link to="/enroll/fix/$field" params={{ field }} className="fact-edit">
                Edit
              </Link>
            </p>
          ))}
        </div>
      </div>
      {canCreate ? null : (
        <p className="note" role="alert">
          A face scan and every required detail are needed before you continue. Address line 2 and address line 3 can
          be left blank.
        </p>
      )}
      <div className="actions">
        {canCreate ? (
          <Link to="/enroll/ready" className="primary">
            Continue
          </Link>
        ) : (
          <button type="button" className="primary" disabled>
            Continue
          </button>
        )}
        <Link
          to="/enroll/capture"
          className="secondary"
          onClick={() => flow.update({ scan: null, photoDataUrl: null })}
        >
          {scanned ? "Scan again" : "Scan your face"}
        </Link>
      </div>
    </Frame>
  );
}
