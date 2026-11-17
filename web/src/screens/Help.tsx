import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Help() {
  const { attemptsLeft } = useFlow();

  return (
    <Frame
      stepIndex={6}
      stepCount={6}
      kicker="Help"
      title="Camera help"
      aside={<p>An officer can review the application instead.</p>}
    >
      <div className="stack">
        {attemptsLeft === 0 ? <p className="note">No attempts left on this browser.</p> : null}
        <p>If the picture is dark, use a window or a lamp. Leave the flash off.</p>
        <div className="panel">
          <p>Common fixes</p>
          <p>Use more light</p>
          <p>Look straight at the camera</p>
          <p>Hold still if the picture is blurry</p>
          <p>Allow the camera in the address bar</p>
        </div>
      </div>
      <div className="actions">
        <Link to="/enroll/capture" className="primary">
          Try again
        </Link>
        <Link to="/enroll/paused" className="secondary">
          I can&apos;t do the face check
        </Link>
      </div>
    </Frame>
  );
}
