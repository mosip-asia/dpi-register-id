import { Link } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";
import { ApplicationSaveNotice, useSaveApplication } from "./saveApplication";

export function Help() {
  const { attemptsLeft } = useFlow();
  const { pending, error, saveApplication } = useSaveApplication();

  return (
    <Frame
      kicker="Help"
      title="Camera help"
      aside={<p>An officer can review the application instead.</p>}
    >
      <div className="stack">
        {attemptsLeft === 0 ? (
          <p className="note" role="alert">
            No attempts left on this browser.
          </p>
        ) : null}
        <p>If the picture is dark, use a window or a lamp. Leave the flash off.</p>
        <div className="panel">
          <strong>Common fixes</strong>
          <p>Allow the camera in the address bar, then try again.</p>
          <p>If the face check does not load, refresh the page. The model is about 12 MB.</p>
          <p>If your face is not found, face a light and sit about an arm's length away.</p>
          <p>If the head turn is missed, turn more slowly and a little further.</p>
        </div>
      </div>
      <ApplicationSaveNotice pending={pending} error={error} />
      <div className="actions">
        <Link
          to="/enroll/capture"
          className="primary"
          onClick={(event) => {
            if (pending) event.preventDefault();
          }}
        >
          Try again
        </Link>
        <button
          type="button"
          className="secondary"
          disabled={pending}
          aria-busy={pending}
          onClick={() => void saveApplication("no-camera")}
        >
          I can't do the face check
        </button>
        <button
          type="button"
          className="secondary"
          disabled={pending}
          aria-busy={pending}
          onClick={() => void saveApplication("camera-quality")}
        >
          The camera is not good enough
        </button>
      </div>
    </Frame>
  );
}
