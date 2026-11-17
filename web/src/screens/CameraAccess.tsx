import { Link } from "@tanstack/react-router";
import { Frame } from "../ui";

export function CameraAccess() {
  return (
    <Frame
      stepIndex={5}
      stepCount={6}
      kicker="Camera"
      title="We need your camera"
      lede="Your browser will ask to use the camera. The camera is only used during the face check."
      aside={
        <>
          <p>If the camera is blocked, check the address bar and choose Allow.</p>
          <p>The first time, the browser downloads the face model, about 12 MB.</p>
        </>
      }
    >
      <div className="actions">
        <Link to="/enroll/capture" className="primary">
          Turn on camera
        </Link>
        <Link to="/enroll/help" className="secondary">
          I don't have a camera
        </Link>
      </div>
    </Frame>
  );
}
