import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { addressFields, addressReady, IdentityField } from "../identityFields";
import { enrollStepCount, Frame } from "../ui";

export function Address() {
  const navigate = useNavigate();
  const flow = useFlow();
  const ready = addressReady(flow);

  return (
    <Frame
      stepIndex={4}
      stepCount={enrollStepCount}
      kicker="Your address"
      title="Your address"
      aside={<p>Address line 2 and address line 3 can be left blank. Every other field is required.</p>}
    >
      <div className="stack">
        {addressFields.map((field) => (
          <IdentityField
            key={field}
            field={field}
            value={flow[field]}
            onChange={(value) => flow.update({ [field]: value })}
          />
        ))}
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!ready}
          onClick={() => navigate({ to: "/enroll/tutorial" })}
        >
          Next
        </button>
      </div>
    </Frame>
  );
}
