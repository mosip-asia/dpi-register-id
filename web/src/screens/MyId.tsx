import { Link, useNavigate } from "@tanstack/react-router";
import { useFlow } from "../flow";
import { Frame } from "../ui";

export function MyId() {
  const navigate = useNavigate();
  const { fullName, uin, recordStatus, reset } = useFlow();

  return (
    <Frame title="My ID">
      {uin ? (
        <div className="stack">
          <p>{fullName}</p>
          <p className="uin">{uin}</p>
        </div>
      ) : (
        <p>No ID yet</p>
      )}
      {recordStatus ? <p>Record status: {recordStatus}</p> : null}
      <p>A face check is a match only when the server says so.</p>
      <p>This page does not hold a login token.</p>
      <div className="actions">
        {uin ? (
          <Link to="/prove" className="primary">
            Use this ID
          </Link>
        ) : (
          <Link to="/enroll/consent" className="primary">
            Start enrollment
          </Link>
        )}
        <Link to="/enroll/details" className="secondary">
          Update details
        </Link>
        <button
          type="button"
          className="quiet"
          onClick={() => {
            reset();
            navigate({ to: "/" });
          }}
        >
          Clear this browser
        </button>
      </div>
    </Frame>
  );
}
