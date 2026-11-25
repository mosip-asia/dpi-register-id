import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { enrollStepCount, Frame } from "../ui";

export function Consent() {
  const navigate = useNavigate();
  const { consentAccepted, researchOptIn, update } = useFlow();

  return (
    <Frame
      stepIndex={2}
      stepCount={enrollStepCount}
      kicker="Consent"
      title="Before we take your photo"
    >
      <div className="stack">
        <div className="panel">
          <strong>Why</strong>
          <p>
            We store your photo and a face signature made in this browser. When you use the ID, a new scan is
            compared with that signature on the server.
          </p>
        </div>
        <div className="panel">
          <strong>Who sees it</strong>
          <p>
            This service stores the photo and the face signature. Other services do not receive the photo.
          </p>
        </div>
        <div className="panel">
          <strong>How long</strong>
          <p>We keep the photo with your ID while that ID is active in this sandbox.</p>
        </div>
        <fieldset className="agreements">
        <legend>Agreement</legend>
        <label className="check">
          <input
            type="checkbox"
            checked={consentAccepted}
            onChange={(event) => update({ consentAccepted: event.target.checked })}
          />
          I agree to create my ID with my face photo.
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={researchOptIn}
            onChange={(event) => update({ researchOptIn: event.target.checked })}
          />
          You may use my photo for research. This is optional.
        </label>
        </fieldset>
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!consentAccepted}
          onClick={() => navigate({ to: "/enroll/details" })}
        >
          I agree, continue
        </button>
      </div>
    </Frame>
  );
}
