import { Link } from "@tanstack/react-router";
import { enrollStepCount, Frame } from "../ui";

export function Landing() {
  return (
    <Frame
      stepIndex={1}
      stepCount={enrollStepCount}
      kicker="Start"
      title="Get your citizen ID from home"
      lede="This creates a sandbox citizen ID you can confirm with your face. You need a webcam or phone camera, an email address, and about 3 minutes. This page does not issue a login token."
    >
      <div className="paths">
        <article className="path">
          <h2>Create an ID</h2>
          <p>A webcam or phone camera, an email address, and about 3 minutes.</p>
          <Link to="/enroll/consent" className="primary">
            Start
          </Link>
        </article>
        <article className="path">
          <h2>Use an existing ID</h2>
          <p>Confirm the number you already have with a face check.</p>
          <Link to="/prove" className="secondary">
            Prove
          </Link>
        </article>
      </div>
    </Frame>
  );
}
