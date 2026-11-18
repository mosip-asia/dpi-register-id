import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

function expiryDate(seconds: number) {
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(seconds * 1000));
}

export function Paused() {
  const { applicationCode, applicationExpiresAt } = useFlow();

  return (
    <Frame kicker="Paused" title="The face check can wait">
      {applicationCode ? (
        <div className="stack">
          <p>Application number</p>
          <p className="uin">{applicationCode}</p>
          {applicationExpiresAt != null ? (
            <p>This application expires on {expiryDate(applicationExpiresAt)}.</p>
          ) : null}
          <p>An officer can review this application later.</p>
          <p>This is not an ID yet.</p>
          <p>This screen does not send email.</p>
        </div>
      ) : (
        <div className="stack">
          <p>The application was not saved.</p>
        </div>
      )}
      <div className="actions">
        <Link to="/" className="primary">
          Done
        </Link>
        {applicationCode ? null : (
          <Link to="/enroll/help" className="secondary">
            Back to help
          </Link>
        )}
      </div>
    </Frame>
  );
}
