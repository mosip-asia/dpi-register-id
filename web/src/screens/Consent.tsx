import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Consent() {
  const navigate = useNavigate();
  const { consentAccepted, researchOptIn, update } = useFlow();

  return (
    <Frame
      stepIndex={2}
      stepCount={6}
      kicker="Consent"
      title="Before we take your photo"
      aside={
        <>
          <h2>How long</h2>
          <p>We keep the photo with your ID while that ID is active in this sandbox.</p>
        </>
      }
    >
      <div className="stack">
        <div className="panel">
          <strong>Why</strong>
          <p>We store a face photo with the draft record. This build does not match that photo to a person.</p>
        </div>
        <div className="panel">
          <strong>Who sees it</strong>
          <p>
            This service stores the photo. It does not send the photo, or a login token, to another service.
          </p>
        </div>
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
