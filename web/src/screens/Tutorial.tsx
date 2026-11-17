import { Link } from "@tanstack/react-router";
import { Frame } from "../ui";

export function Tutorial() {
  return (
    <Frame
      stepIndex={4}
      stepCount={6}
      kicker="Face check"
      title="How the face check works"
      lede="You take one photo. The server stores it with the draft. It does not match a face."
      aside={
        <>
          <h2>Don't</h2>
          <ul>
            <li>No glasses</li>
            <li>No hat or mask</li>
            <li>No second screen</li>
          </ul>
        </>
      }
    >
      <div className="panel">
        <strong>Do</strong>
        <ul>
          <li>Good light</li>
          <li>Face in the oval</li>
          <li>Look at the camera</li>
        </ul>
      </div>
      <div className="actions">
        <Link to="/enroll/camera" className="primary">
          I'm ready
        </Link>
      </div>
    </Frame>
  );
}
