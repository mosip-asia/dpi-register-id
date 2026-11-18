import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { IdCard } from "../IdCard";
import { useFlow } from "../flow";
import { CopyValue, Frame } from "../ui";

export function MyId() {
  const navigate = useNavigate();
  const { fullName, dateOfBirth, uin, recordStatus, reset } = useFlow();
  const [confirmClear, setConfirmClear] = useState(false);

  return (
    <Frame title="My ID">
      {uin ? (
        <div className="stack">
          <div className="uin-row">
            <p className="uin">{uin}</p>
            <CopyValue value={uin} />
          </div>
          <IdCard uin={uin} fullName={fullName} dateOfBirth={dateOfBirth} />
        </div>
      ) : (
        <div className="panel">
          <p>No ID yet</p>
        </div>
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
            if (!confirmClear) {
              setConfirmClear(true);
              return;
            }
            reset();
            navigate({ to: "/" });
          }}
        >
          {confirmClear ? "Confirm clear" : "Clear this browser"}
        </button>
      </div>
    </Frame>
  );
}
