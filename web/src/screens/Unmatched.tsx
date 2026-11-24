import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Unmatched() {
  const { lastMessage, attemptsLeft } = useFlow();

  return (
    <Frame
      stepIndex={4}
      stepCount={4}
      kicker="Unmatched"
      title="This face did not match the ID"
      lede="You can try again while attempts remain."
    >
      <p>{lastMessage ?? "No face check has been sent from this browser."}</p>
      <p>Attempts left: {attemptsLeft}</p>
      {attemptsLeft > 0 ? null : (
        <p className="callout" role="status">
          No attempts left. An officer can review the application.
        </p>
      )}
      <div className="actions">
        {attemptsLeft > 0 ? (
          <Link to="/prove/check" className="primary">
            Try again
          </Link>
        ) : null}
        <Link to="/enroll/help" className="secondary">
          Get help
        </Link>
        <Link to="/id/activity" className="secondary">
          My activity
        </Link>
      </div>
    </Frame>
  );
}
