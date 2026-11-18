import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Paused() {
  const { uin } = useFlow();

  return (
    <Frame kicker="Paused" title="The face check can wait">
      <div className="stack">
        <p>You can stop here and come back on this browser.</p>
        <strong>Application number</strong>
        {uin ? <p className="uin">{uin}</p> : <p>Not issued yet</p>}
        <p>An officer can review the application later.</p>
        <p>This screen does not send email.</p>
        <p>You can try again later from another device.</p>
      </div>
      <div className="actions">
        <Link to="/" className="primary">
          Done
        </Link>
      </div>
    </Frame>
  );
}
