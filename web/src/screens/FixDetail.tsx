import { Link, useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function FixDetail() {
  const navigate = useNavigate();
  const { dateOfBirth, email, update } = useFlow();
  const dateEmpty = dateOfBirth.trim() === "";
  const emailTrimmed = email.trim();
  const emailInvalid = emailTrimmed !== "" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailTrimmed);

  return (
    <Frame kicker="Fix" title="Fix date of birth or email">
      <div className="stack">
        <label>
          Date of birth
          <input
            type="date"
            value={dateOfBirth}
            autoComplete="bday"
            onChange={(event) => update({ dateOfBirth: event.target.value })}
          />
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            autoComplete="email"
            aria-invalid={emailInvalid || undefined}
            onChange={(event) => update({ email: event.target.value })}
          />
        </label>
        {dateEmpty ? (
          <p className="note" role="alert">
            The date looks empty.
          </p>
        ) : null}
        {emailInvalid ? (
          <p className="note" role="alert">
            Enter an email address with a name, an @ sign, and a domain.
          </p>
        ) : null}
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={dateEmpty || emailInvalid || emailTrimmed === ""}
          onClick={() => navigate({ to: "/enroll/review" })}
        >
          Save and go back
        </button>
        <Link to="/enroll/review" className="secondary">
          Cancel
        </Link>
      </div>
    </Frame>
  );
}
