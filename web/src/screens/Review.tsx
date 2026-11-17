import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Review() {
  const { photoDataUrl, scan, fullName, gender, dateOfBirth, email, update } = useFlow();
  const canCreate = Boolean(photoDataUrl && scan && fullName.trim() && email.trim());

  return (
    <Frame stepIndex={6} stepCount={6} kicker="Review" title="Check before we create your ID">
      <div className="stack">
        {photoDataUrl ? (
          <img alt="Your ID photo" src={photoDataUrl} className="photo" />
        ) : (
          <div className="panel">
            <p>No photo yet.</p>
            <Link to="/enroll/capture">Scan your face</Link>
          </div>
        )}
        <p>
          Face scan done: the head turn was checked in this browser.{" "}
          <Link
            to="/enroll/capture"
            onClick={() => update({ scan: null, photoDataUrl: null })}
          >
            Scan again
          </Link>
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
        <Link to="/enroll/fix">Edit</Link>
      </div>
      <div className="actions">
        {canCreate ? (
          <Link to="/enroll/ready" className="primary">
            Create my ID
          </Link>
        ) : (
          <button type="button" className="primary" disabled>
            Create my ID
          </button>
        )}
      </div>
    </Frame>
  );
}
