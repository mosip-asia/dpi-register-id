import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Review() {
  const { photoDataUrl, scan, fullName, gender, dateOfBirth, email, update } = useFlow();
  const scanned = Boolean(photoDataUrl && scan);
  const canCreate = Boolean(
    scanned && fullName.trim() && gender.trim() && dateOfBirth.trim() && email.trim(),
  );

  return (
    <Frame stepIndex={7} stepCount={8} kicker="Review" title="Check before we create your ID">
      <div className="stack">
        {photoDataUrl ? (
          <img alt="Preview of the photo that will be stored with your ID" src={photoDataUrl} className="photo" />
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
          <p>
            <strong>Full name</strong> <span>{fullName}</span>
          </p>
          <p>
            <strong>Gender</strong> <span>{gender}</span>
          </p>
          <p>
            <strong>Date of birth</strong> <span>{dateOfBirth}</span>
          </p>
          <p>
            <strong>Email</strong> <span>{email}</span>
          </p>
        </div>
      </div>
      {canCreate ? null : (
        <p className="note" role="alert">
          A face scan, name, gender, date of birth, and email are required before you continue.
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
          onClick={() => update({ scan: null, photoDataUrl: null })}
        >
          {scanned ? "Scan again" : "Scan your face"}
        </Link>
        <Link to="/enroll/fix" className="secondary">
          Edit date or email
        </Link>
      </div>
    </Frame>
  );
}
