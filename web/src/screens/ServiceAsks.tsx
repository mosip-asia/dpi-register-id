import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function ServiceAsks() {
  const { serviceName } = useFlow();

  return (
    <Frame
      stepIndex={1}
      stepCount={4}
      kicker="Service"
      title={`${serviceName} wants to confirm it is you`}
    >
      <p>A connected service would see the name, the UIN, and whether the server confirmed the face.</p>
      <p>This build does not send a password or a login token.</p>
      <div className="actions">
        <Link to="/prove/id" className="primary">
          Continue
        </Link>
        <Link to="/" className="quiet">
          Cancel and go back
        </Link>
      </div>
    </Frame>
  );
}
