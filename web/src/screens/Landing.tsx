import { Link } from "@tanstack/react-router";
import { Frame } from "../ui";

export function Landing() {
  return (
    <Frame
      stepIndex={1}
      stepCount={6}
      kicker="Start"
      title="Get your citizen ID from home"
      lede="This creates a sandbox citizen ID you can confirm with your face. You need a webcam or phone camera, an email address, and about 3 minutes. This page does not issue a login token."
    >
      <div className="actions">
        <Link to="/enroll/consent" className="primary">
          Start
        </Link>
        <Link to="/prove" className="quiet">
          Already have an ID? Use it
        </Link>
      </div>
    </Frame>
  );
}
