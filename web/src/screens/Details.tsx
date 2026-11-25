import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { detailFields, detailsReady, emailInvalid, IdentityField } from "../identityFields";
import { enrollStepCount, Frame } from "../ui";

export function Details() {
  const navigate = useNavigate();
  const flow = useFlow();
  const ready = flow.consentAccepted && detailsReady(flow);

  return (
    <Frame
      stepIndex={3}
      stepCount={enrollStepCount}
      kicker="Your details"
      title="Your details"
      aside={
        <p>
          Every field on this page is required. The reference ID number can be a national ID or a student ID.
        </p>
      }
    >
      <div className="stack">
        {detailFields.map((field) => (
          <IdentityField
            key={field}
            field={field}
            value={flow[field]}
            onChange={(value) => flow.update({ [field]: value })}
          />
        ))}
      </div>
      {emailInvalid(flow.email) ? (
        <p className="note" role="alert">
          Enter an email address with a name, an @ sign, and a domain.
        </p>
      ) : null}
      {flow.consentAccepted ? null : (
        <p className="note" role="alert">
          Agree to the photo consent before these details.
        </p>
      )}
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!ready}
          onClick={() => navigate({ to: "/enroll/address" })}
        >
          Next
        </button>
      </div>
    </Frame>
  );
}
