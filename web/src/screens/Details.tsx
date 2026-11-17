import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Details() {
  const navigate = useNavigate();
  const { fullName, dateOfBirth, gender, email, consentAccepted, update } = useFlow();
  const ready =
    consentAccepted &&
    fullName.trim() !== "" &&
    dateOfBirth.trim() !== "" &&
    gender.trim() !== "" &&
    email.trim() !== "";

  return (
    <Frame
      stepIndex={3}
      stepCount={6}
      kicker="Details"
      title="Tell us about you"
      aside={<p>Next turns on when these are filled.</p>}
    >
      <div className="stack">
        <label>
          Full name
          <input
            value={fullName}
            autoComplete="name"
            onChange={(event) => update({ fullName: event.target.value })}
          />
        </label>
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
          Gender
          <select
            value={gender}
            onChange={(event) => update({ gender: event.target.value })}
          >
            <option value=""></option>
            <option>Female</option>
            <option>Male</option>
            <option>Another</option>
            <option>Prefer not to say</option>
          </select>
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            autoComplete="email"
            onChange={(event) => update({ email: event.target.value })}
          />
        </label>
      </div>
      {consentAccepted ? null : (
        <p className="note">Agree to the photo consent before these details.</p>
      )}
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
