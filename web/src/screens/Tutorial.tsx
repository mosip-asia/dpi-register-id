import { Link } from "@tanstack/react-router";
import { Frame } from "../ui";

export function Tutorial() {
  return (
    <Frame
      stepIndex={4}
      stepCount={8}
      kicker="Face check"
      title="How the face check works"
      lede="The scan takes about 20 seconds. The face model runs in this browser. At the end, your photo and a face signature go to the server."
    >
      <div className="stack">
      <div className="panel">
        <strong>Do</strong>
        <ul>
          <li>Use good light</li>
          <li>Put your face in the oval</li>
          <li>Turn your head slowly to your left, then to your right</li>
          <li>Look at the camera</li>
        </ul>
      </div>
      <div className="panel">
        <strong>Don't</strong>
        <ul>
          <li>No glasses</li>
          <li>No hat or mask</li>
          <li>No second screen</li>
          <li>No one else in view</li>
        </ul>
      </div>
      </div>
      <div className="actions">
        <Link to="/enroll/camera" className="primary">
          I'm ready
        </Link>
      </div>
    </Frame>
  );
}
