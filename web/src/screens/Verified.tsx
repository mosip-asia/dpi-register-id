import { Link, Navigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Verified() {
  const { fullName, verified } = useFlow();
  const given = fullName.trim().split(/\s+/)[0] ?? "";
  const title = given ? `It's you, ${given}` : "It's you";

  if (!verified) return <Navigate to="/prove/check" />;

  return (
    <Frame stepIndex={3} stepCount={3} kicker="Verified" title={title}>
      <p>The server reported a face match for this ID. This page does not send a login token.</p>
      <div className="actions">
        <Link to="/id" className="primary">
          My ID
        </Link>
      </div>
    </Frame>
  );
}
