import { Link, Navigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Verified() {
  const { fullName, verified, uin } = useFlow();
  const given = fullName.trim().split(/\s+/)[0] ?? "";
  const title = given ? `It's you, ${given}` : "It's you";

  if (!verified) return <Navigate to="/prove/check" />;

  return (
    <Frame
      stepIndex={4}
      stepCount={4}
      kicker="Verified"
      title={title}
      aside={<p>The head turn was checked in this browser. This page does not issue a login token.</p>}
    >
      <div className="success">
        <p>The server matched this face to ID {uin}.</p>
      </div>
      <div className="actions">
        <Link to="/id" className="primary">
          My ID
        </Link>
      </div>
    </Frame>
  );
}
