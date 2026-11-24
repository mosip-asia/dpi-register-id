import { Link } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";
import { activityToken, ApiError, myActivity, reportNotMe, type IdentityCheck } from "../api";
import { useFlow } from "../flow";
import { CopyValue, Frame } from "../ui";

function errorMessage(caught: unknown) {
  if (caught instanceof ApiError) return caught.message;
  if (caught instanceof Error && caught.message) return caught.message;
  return "The request failed.";
}

function formatWhen(when: number | undefined) {
  if (when == null || !Number.isFinite(when)) return "";
  const ms = Math.abs(when) < 1e12 ? when * 1000 : when;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function eventName(check: IdentityCheck) {
  return (check.event ?? check.kind ?? "").trim().toLowerCase();
}

function citizenLine(check: IdentityCheck) {
  const message = check.message?.trim() ?? "";
  if (message) return message;
  const result = (check.result ?? "").trim();
  const event = eventName(check);
  if (result.toLowerCase() === "success" && event === "authenticate") return "Your face check passed";
  if (result.toLowerCase() === "success" && event === "enroll") return "Your ID was created";
  return result;
}

function isAuthenticate(check: IdentityCheck) {
  return eventName(check) === "authenticate";
}

function canDispute(check: IdentityCheck, reported: Set<string>) {
  return Boolean(check.checkId && isAuthenticate(check) && !reported.has(check.checkId));
}

function outcome(check: IdentityCheck) {
  const result = (check.result ?? "").trim().toLowerCase();
  const event = eventName(check);
  if (event === "activity_reported") return { label: "Reported", tone: "reported" };
  if (result === "success" && event === "enroll") return { label: "Created", tone: "pass" };
  if (result === "success") return { label: "Passed", tone: "pass" };
  if (result === "failure") return { label: "Failed", tone: "fail" };
  return { label: result || "Recorded", tone: "recorded" };
}

export function Activity() {
  const token = activityToken();
  const flow = useFlow();
  const [checks, setChecks] = useState<IdentityCheck[]>([]);
  const [uin, setUin] = useState<string | null>(flow.uin);
  const [triesUsed, setTriesUsed] = useState<number | null>(null);
  const [askWasThisYou, setAskWasThisYou] = useState(false);
  const [reported, setReported] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let active = true;
    myActivity(token)
      .then((report) => {
        if (!active) return;
        setChecks(report.checks);
        setUin(report.uin ?? flow.uin);
        setTriesUsed(report.triesUsed ?? null);
        setReported(new Set(report.disputes));
        setAskWasThisYou(report.askWasThisYou === true);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setError(errorMessage(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token, flow.uin]);

  async function onNotMe(event: FormEvent, checkId: string) {
    event.preventDefault();
    if (!token || pendingId) return;
    setPendingId(checkId);
    setError(null);
    try {
      await reportNotMe(token, checkId, detail);
      setReported((current) => new Set(current).add(checkId));
      setDetail("");
      setOpenId(null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPendingId(null);
    }
  }

  if (!token) {
    return (
      <Frame wide title="My activity" lede="Prove your ID to see who checked it.">
        <div className="dash-actions">
          <Link to="/prove" className="primary">
            Prove your ID
          </Link>
        </div>
      </Frame>
    );
  }

  const name = flow.fullName.trim() || "Your ID";
  const shownUin = uin || flow.uin || "";
  const reportTarget = checks.find((check) => canDispute(check, reported));
  const reportId = reportTarget?.checkId;

  return (
    <Frame wide title={name} lede="Who checked this ID in this browser session.">
      <div className="dash">
        <section className="dash-id">
          <div>
            <p className="dash-kicker">My activity</p>
            {shownUin ? (
              <p className="uin-row">
                <span className="uin">{shownUin}</span>
                <CopyValue value={shownUin} />
              </p>
            ) : (
              <p>No UIN on this session yet.</p>
            )}
          </div>
          <span className={askWasThisYou ? "dash-status is-hold" : "dash-status"}>{askWasThisYou ? "Visit the office" : "Active"}</span>
        </section>

        <div className="dash-actions">
          <Link to="/id" className="secondary">
            ID card
          </Link>
          <Link to="/enroll/details" className="secondary">
            Update details
          </Link>
          <Link to="/prove" className="primary">
            Prove this ID
          </Link>
        </div>

        <dl className="dash-stats">
          <div>
            <dt>Checks</dt>
            <dd>{loading ? "…" : checks.length}</dd>
          </div>
          <div>
            <dt>Tries used</dt>
            <dd>{triesUsed == null ? "—" : `${triesUsed} of 3`}</dd>
          </div>
          <div>
            <dt>Reports</dt>
            <dd>{reported.size}</dd>
          </div>
        </dl>

        {error ? (
          <p className="note" role="alert">
            {error} <Link to="/prove">Prove your ID</Link>
          </p>
        ) : null}
        {askWasThisYou ? (
          <p className="callout">An officer needs to check this. Visit the office with your code.</p>
        ) : null}

        <section className="dash-log-wrap">
          <h2>Who checked this ID</h2>
          {loading ? (
            <p className="status" role="status" aria-busy="true">
              Loading activity…
            </p>
          ) : checks.length === 0 ? (
            <p className="dash-empty">No checks yet. A face check will show up here.</p>
          ) : (
            <ul className="dash-log">
              {checks.map((check, index) => {
                const checkId = check.checkId;
                const disputed = Boolean(checkId && reported.has(checkId));
                const result = outcome(check);
                return (
                  <li key={checkId ?? check.eventId ?? `check-${index}`}>
                    <span className={`dash-result is-${result.tone}`}>{result.label}</span>
                    <div>
                      <p>{citizenLine(check)}</p>
                      <p className="dash-meta">
                        {formatWhen(check.when)}
                        {check.device ? ` · ${check.device}` : ""}
                        {disputed ? " · You reported this" : ""}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {reportId ? (
          <section className="dash-report">
            {openId === reportId ? (
              <form onSubmit={(event) => void onNotMe(event, reportId)}>
                <label htmlFor="not-me-detail">
                  What should the officer know?
                  <input
                    id="not-me-detail"
                    value={detail}
                    onChange={(event) => setDetail(event.target.value)}
                  />
                </label>
                <div className="dash-actions">
                  <button
                    type="submit"
                    className="primary"
                    disabled={pendingId === reportId}
                    aria-busy={pendingId === reportId}
                  >
                    Send report
                  </button>
                  <button type="button" className="quiet" onClick={() => setOpenId(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button type="button" className="quiet" onClick={() => setOpenId(reportId)}>
                Not you? Report this to an officer
              </button>
            )}
          </section>
        ) : null}
      </div>
    </Frame>
  );
}
