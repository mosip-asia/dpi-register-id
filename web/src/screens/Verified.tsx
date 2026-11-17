import { Link, Navigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Verified() {
  const { fullName, verified, uin, lastDistance } = useFlow();
  const given = fullName.trim().split(/\s+/)[0] ?? "";
  const title = given ? `It's you, ${given}` : "It's you";
  const distance = lastDistance === null ? null : lastDistance.toFixed(2);

  if (!verified) return <Navigate to="/prove/check" />;

  return (
    <Frame
      stepIndex={3}
      stepCount={3}
      kicker="Verified"
      title={title}
      aside={
        <>
          {distance ? <p>Distance {distance} is under the 0.5 threshold.</p> : null}
          <p>The head turn was checked in this browser. This page does not issue a login token.</p>
        </>
      }
    >
      <p>The server matched this face to ID {uin}.</p>
      <div className="actions">
        <Link to="/id" className="primary">
          My ID
        </Link>
      </div>
    </Frame>
  );
}
