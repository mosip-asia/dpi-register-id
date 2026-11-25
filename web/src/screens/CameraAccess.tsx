import { Link } from "@tanstack/react-router";
import { reportAttempt } from "../api";
import { enrollStepCount, Frame } from "../ui";
import { ApplicationSaveNotice, useSaveApplication } from "./saveApplication";

export function CameraAccess() {
  const { pending, error, saveApplication } = useSaveApplication();

  return (
    <Frame
      stepIndex={6}
      stepCount={enrollStepCount}
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
      <ApplicationSaveNotice pending={pending} error={error} />
      <div className="actions">
        <Link
          to="/enroll/capture"
          className="primary"
          onClick={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          Continue
        </Link>
        <button
          type="button"
          className="secondary"
          disabled={pending}
          aria-busy={pending}
          onClick={() => {
            reportAttempt({ kind: "camera", reasonCode: "camera_unavailable", detail: "no camera" });
            void saveApplication("no-camera");
          }}
        >
          I don't have a camera
        </button>
      </div>
    </Frame>
  );
}
