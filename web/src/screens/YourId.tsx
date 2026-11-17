import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function YourId() {
  const navigate = useNavigate();
  const { uin, update } = useFlow();
  const empty = (uin ?? "").trim() === "";

  return (
    <Frame stepIndex={2} stepCount={3} kicker="Your ID" title="Which ID is yours?">
      <div className="stack">
        <label>
          ID number
          <input
            value={uin ?? ""}
            autoComplete="off"
            onChange={(event) => update({ uin: event.target.value })}
          />
        </label>
        <p>Forgot your ID? The number is on the ready screen after enrollment.</p>
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={empty}
          onClick={() => navigate({ to: "/prove/check" })}
        >
          Continue
        </button>
      </div>
    </Frame>
  );
}
