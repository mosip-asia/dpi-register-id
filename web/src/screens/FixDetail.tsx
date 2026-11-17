import { Link, useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function FixDetail() {
  const navigate = useNavigate();
  const { dateOfBirth, email, update } = useFlow();
  const dateEmpty = dateOfBirth.trim() === "";

  return (
    <Frame stepIndex={6} stepCount={6} kicker="Fix" title="Something wrong?">
      <div className="stack">
        <label>
          Date of birth
          <input
            type="date"
            value={dateOfBirth}
            onChange={(event) => update({ dateOfBirth: event.target.value })}
          />
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => update({ email: event.target.value })}
          />
        </label>
        {dateEmpty ? <p className="note">The date looks empty.</p> : null}
      </div>
      <div className="actions">
        <button type="button" className="primary" onClick={() => navigate({ to: "/enroll/review" })}>
          Save and go back
        </button>
        <Link to="/enroll/review" className="secondary">
          Cancel
        </Link>
      </div>
    </Frame>
  );
}
