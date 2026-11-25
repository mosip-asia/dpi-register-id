import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect } from "react";
import { useFlow } from "../flow";
import { emailInvalid, fieldMeta, fieldOk, IdentityField, isCitizenField } from "../identityFields";
import { Frame } from "../ui";

export function FixDetail() {
  const navigate = useNavigate();
  const flow = useFlow();
  const { field: rawField } = useParams({ strict: false });
  const field = typeof rawField === "string" && isCitizenField(rawField) ? rawField : null;

  useEffect(() => {
    if (!field) return;
    document.getElementById(`field-${field}`)?.focus();
  }, [field]);

  if (!field) {
    return (
      <Frame kicker="Fix" title="Fix a detail">
        <p className="note" role="alert">
          That detail is not on this form.
        </p>
        <div className="actions">
          <Link to="/enroll/review" className="primary">
            Back to review
          </Link>
        </div>
      </Frame>
    );
  }

  const value = flow[field];
  const meta = fieldMeta[field];
  const canSave = fieldOk(field, value);

  return (
    <Frame kicker="Fix" title="Fix a detail" lede={meta.label}>
      <div className="stack">
        <IdentityField field={field} value={value} onChange={(next) => flow.update({ [field]: next })} />
        {field === "dateOfBirth" && value.trim() === "" ? (
          <p className="note" role="alert">
            The date looks empty.
          </p>
        ) : null}
        {field === "email" && emailInvalid(value) ? (
          <p className="note" role="alert">
            Enter an email address with a name, an @ sign, and a domain.
          </p>
        ) : null}
        {field !== "dateOfBirth" && field !== "email" && !meta.optional && value.trim() === "" ? (
          <p className="note" role="alert">
            This field is required.
          </p>
        ) : null}
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!canSave}
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
