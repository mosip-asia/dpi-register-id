import { useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function Details() {
  const navigate = useNavigate();
  const { fullName, dateOfBirth, gender, email, consentAccepted, update } = useFlow();
  const emailTrimmed = email.trim();
  const emailInvalid = emailTrimmed !== "" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailTrimmed);
  const ready =
    consentAccepted &&
    fullName.trim() !== "" &&
    dateOfBirth.trim() !== "" &&
    gender.trim() !== "" &&
    emailTrimmed !== "" &&
    !emailInvalid;

  return (
    <Frame
      stepIndex={3}
      stepCount={8}
      kicker="Details"
      title="Tell us about you"
      aside={<p>All fields are required before you can continue.</p>}
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
            <option value="">Select</option>
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
            aria-invalid={emailInvalid || undefined}
            onChange={(event) => update({ email: event.target.value })}
          />
        </label>
      </div>
      {emailInvalid ? (
        <p className="note" role="alert">
          Enter an email address with a name, an @ sign, and a domain.
        </p>
      ) : null}
      {consentAccepted ? null : (
        <p className="note" role="alert">
          Agree to the photo consent before these details.
        </p>
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
