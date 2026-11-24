import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  addStaff,
  ApiError,
  deleteSavedFace,
  DESK_TOKEN_KEY,
  deskSession,
  getCitizen,
  getCitizenChecks,
  listChecks,
  listReports,
  listStaff,
  markReportChecked,
  openReport,
  removeStaff,
  searchAudit,
  searchCitizens,
  setCitizenLock,
  setLoginDisabled,
  setStaffRole,
  updateDemographics,
  type CitizenRecord,
  type CitizenReport,
  type CitizenSummary,
  type IdentityCheck,
  type StaffMember,
} from "../api";
import { CopyValue, Frame } from "../ui";

const REASON_MIN = 3;

function reasonOk(value: string) {
  return value.trim().length >= REASON_MIN;
}

function emailOk(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

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

function formatScore(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
}

function yesNo(value: boolean | undefined) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "";
}

function ReasonField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const short = value.trim() !== "" && !reasonOk(value);
  return (
    <label className="block" htmlFor={id}>
      Reason
      <textarea
        id={id}
        value={value}
        required
        minLength={REASON_MIN}
        aria-invalid={short || undefined}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function Desk() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(DESK_TOKEN_KEY));
  const [draft, setDraft] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [checking, setChecking] = useState(() => Boolean(sessionStorage.getItem(DESK_TOKEN_KEY)));
  const [role, setRole] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const flight = useRef<string | null>(null);

  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState(false);
  const [results, setResults] = useState<CitizenSummary[]>([]);
  const [person, setPerson] = useState<CitizenRecord | null>(null);
  const [checks, setChecks] = useState<IdentityCheck[]>([]);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [demoReason, setDemoReason] = useState("");
  const [loginReason, setLoginReason] = useState("");
  const [lockReason, setLockReason] = useState("");
  const [faceReason, setFaceReason] = useState("");
  const [faceNote, setFaceNote] = useState<string | null>(null);

  const [auditUin, setAuditUin] = useState("");
  const [auditApp, setAuditApp] = useState("");
  const [auditSession, setAuditSession] = useState("");
  const [auditDate, setAuditDate] = useState("");
  const [auditSearched, setAuditSearched] = useState(false);
  const [auditRows, setAuditRows] = useState<IdentityCheck[]>([]);

  const [reports, setReports] = useState<CitizenReport[]>([]);
  const [reportsLoaded, setReportsLoaded] = useState(false);
  const [reportsVersion, setReportsVersion] = useState(0);
  const [reportReasons, setReportReasons] = useState<Record<string, string>>({});
  const [reportNotes, setReportNotes] = useState<Record<string, string>>({});

  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [allChecks, setAllChecks] = useState<IdentityCheck[]>([]);
  const [listsLoaded, setListsLoaded] = useState(false);
  const [listsVersion, setListsVersion] = useState(0);
  const [staffName, setStaffName] = useState("");
  const [staffEmail, setStaffEmail] = useState("");
  const [staffRole, setStaffRolePick] = useState<"officer" | "admin">("officer");
  const [staffReason, setStaffReason] = useState("");
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [rowReasons, setRowReasons] = useState<Record<string, string>>({});
  const [rowRoles, setRowRoles] = useState<Record<string, "officer" | "admin">>({});

  const normalizedRole = (role ?? "").trim().toLowerCase();
  const canCorrect = normalizedRole === "officer" || normalizedRole === "admin" || normalizedRole === "custodian";
  const canManage = normalizedRole === "admin" || normalizedRole === "custodian";

  function reject(caught: unknown) {
    if (caught instanceof ApiError && caught.status === 401) {
      sessionStorage.removeItem(DESK_TOKEN_KEY);
      setToken(null);
      setRole(null);
      setIssuedToken(null);
      setError("That token was not recognized.");
      return;
    }
    setError(errorMessage(caught));
  }

  useEffect(() => {
    if (!token) return;
    let active = true;
    setChecking(true);
    deskSession(token)
      .then((session) => {
        if (!active) return;
        setRole(session.role.trim().toLowerCase());
        setDraft("");
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setRole(null);
        reject(caught);
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
    // reject is recreated each render and only calls setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, attempt]);

  useEffect(() => {
    if (!token || !canManage) return;
    let active = true;
    setListsLoaded(false);
    Promise.all([listStaff(token), listChecks(token)])
      .then(([members, rows]) => {
        if (!active) return;
        setStaff(members);
        setAllChecks(rows);
        setRowRoles((current) => {
          const next = { ...current };
          for (const member of members) {
            next[member.id] = member.role === "admin" ? "admin" : "officer";
          }
          return next;
        });
      })
      .catch((caught: unknown) => {
        if (active) reject(caught);
      })
      .finally(() => {
        if (active) setListsLoaded(true);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, canManage, listsVersion]);

  useEffect(() => {
    if (!token || !role) return;
    let active = true;
    setReportsLoaded(false);
    listReports(token)
      .then((rows) => {
        if (active) setReports(rows);
      })
      .catch((caught: unknown) => {
        if (active) reject(caught);
      })
      .finally(() => {
        if (active) setReportsLoaded(true);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role, reportsVersion]);

  function signOut() {
    sessionStorage.removeItem(DESK_TOKEN_KEY);
    setToken(null);
    setRole(null);
    setDraft("");
    setError(null);
    setIssuedToken(null);
    setPerson(null);
    setChecks([]);
    setResults([]);
    setLockReason("");
    setAuditRows([]);
    setAuditSearched(false);
    setReports([]);
    setReportReasons({});
    setReportNotes({});
    setBusy(null);
  }

  async function run(key: string, task: () => Promise<void>) {
    if (flight.current) return;
    flight.current = key;
    setBusy(key);
    setError(null);
    try {
      await task();
    } catch (caught) {
      reject(caught);
    } finally {
      if (flight.current === key) flight.current = null;
      setBusy(null);
    }
  }

  function onContinue(event: FormEvent) {
    event.preventDefault();
    const next = draft.trim();
    if (!next || checking) return;
    setError(null);
    setChecking(true);
    sessionStorage.setItem(DESK_TOKEN_KEY, next);
    setToken(next);
    setAttempt((current) => current + 1);
  }

  async function openPerson(uin: string) {
    if (!token) return;
    await run("person", async () => {
      setFaceNote(null);
      const record = await getCitizen(token, uin);
      setPerson(record);
      setFullName(record.fullName);
      setEmail(record.email ?? "");
      setDemoReason("");
      setLoginReason("");
      setLockReason("");
      setFaceReason("");
      try {
        setChecks(await getCitizenChecks(token, uin));
      } catch (caught) {
        setChecks([]);
        throw caught;
      }
    });
  }

  if (!token || !role) {
    return (
      <Frame wide title="Staff desk" lede="Enter the staff token to continue.">
        {token && checking ? (
          <>
            <p className="status" role="status">
              Checking access…
            </p>
            <div className="actions">
              <button type="button" className="quiet" onClick={signOut}>
                Sign out
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={onContinue}>
            {error ? (
              <p className="note" role="alert">
                {error}
              </p>
            ) : null}
            <div className="stack">
              <label htmlFor="staff-token">
                Staff token
                <input
                  id="staff-token"
                  type="password"
                  value={draft}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>
            </div>
            <div className="actions">
              <button type="submit" className="primary" disabled={checking || draft.trim() === ""}>
                Continue
              </button>
              {token ? (
                <button
                  type="button"
                  className="secondary"
                  disabled={checking}
                  onClick={() => {
                    setError(null);
                    setAttempt((current) => current + 1);
                  }}
                >
                  Try again
                </button>
              ) : null}
              {token ? (
                <button type="button" className="quiet" onClick={signOut}>
                  Sign out
                </button>
              ) : null}
            </div>
          </form>
        )}
      </Frame>
    );
  }

  const sessionToken = token;
  const emailInvalid = email.trim() !== "" && !emailOk(email);
  const staffEmailInvalid = staffEmail.trim() !== "" && !emailOk(staffEmail);
  const demoReady = fullName.trim() !== "" && emailOk(email) && reasonOk(demoReason);
  const addReady =
    staffName.trim() !== "" && emailOk(staffEmail) && reasonOk(staffReason) && busy !== "add-staff";

  return (
    <Frame wide title="Staff desk" lede="Search for a person, then review their identity checks.">
      <p className="role-chip">Role: {normalizedRole}</p>
      {error ? (
        <p className="note" role="alert">
          {error}
        </p>
      ) : null}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void run("search", async () => {
            setResults(await searchCitizens(sessionToken, query.trim()));
            setSearched(true);
          });
        }}
      >
        <div className="stack">
          <label htmlFor="citizen-search">
            Search
            <input
              id="citizen-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>
        <div className="actions">
          <button type="submit" className="primary" disabled={busy === "search"} aria-busy={busy === "search"}>
            Search
          </button>
        </div>
      </form>

      {searched && results.length === 0 ? <p>No one matched that search.</p> : null}
      {results.length > 0 ? (
        <ul className="pick-list">
          {results.map((item) => (
            <li key={item.uin}>
              <button
                type="button"
                className="pick"
                aria-current={person?.uin === item.uin ? "true" : undefined}
                onClick={() => void openPerson(item.uin)}
              >
                <span>{item.fullName || "No name"}</span>
                {item.email ? <span>{item.email}</span> : null}
                <span className="uin">{item.uin}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {busy === "person" ? (
        <p className="status" role="status" aria-busy="true">
          Loading this person…
        </p>
      ) : null}

      {person ? (
        <section>
          <h2>{person.fullName || "Person"}</h2>
          <div className="facts">
            <p>
              <strong>Email</strong> <span>{person.email || "No email"}</span>
            </p>
            <p>
              <strong>UIN</strong> <span className="uin">{person.uin}</span>
            </p>
            <p>
              <strong>Login</strong> <span>{person.loginDisabled ? "Login off" : "Login allowed"}</span>
            </p>
            {person.locked === true || person.locked === false ? (
              <p>
                <strong>ID</strong> <span>{person.locked ? "Locked" : "Unlocked"}</span>
              </p>
            ) : null}
          </div>

          {checks.length === 0 ? (
            <p>No identity checks for this person.</p>
          ) : (
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Result</th>
                    <th scope="col">Liveness</th>
                    <th scope="col">Match</th>
                    <th scope="col">Liveness score</th>
                    <th scope="col">Match score</th>
                    <th scope="col">Network</th>
                    <th scope="col">Browser</th>
                    <th scope="col">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.map((check, index) => (
                    <tr key={check.checkId ?? `${check.when ?? "check"}-${index}`}>
                      <td>{formatWhen(check.when)}</td>
                      <td>{check.result ?? ""}</td>
                      <td>{yesNo(check.livenessPassed)}</td>
                      <td>{yesNo(check.matchPassed)}</td>
                      <td>{formatScore(check.livenessScore)}</td>
                      <td>{formatScore(check.matchScore)}</td>
                      <td>{check.network ?? ""}</td>
                      <td>{check.browser ?? ""}</td>
                      <td>{check.reasonCode ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {canCorrect ? (
          <>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!demoReady) return;
              void run("demographics", async () => {
                const nextName = fullName.trim();
                const nextEmail = email.trim();
                await updateDemographics(sessionToken, person.uin, {
                  fullName: nextName,
                  email: nextEmail,
                  reason: demoReason.trim(),
                });
                setPerson({ ...person, fullName: nextName, email: nextEmail });
                setFullName(nextName);
                setEmail(nextEmail);
                setDemoReason("");
              });
            }}
          >
            <h2>Correct name and email</h2>
            <div className="stack">
              <label htmlFor="citizen-name">
                Full name
                <input id="citizen-name" value={fullName} onChange={(event) => setFullName(event.target.value)} />
              </label>
              <label htmlFor="citizen-email">
                Email
                <input
                  id="citizen-email"
                  type="email"
                  value={email}
                  aria-invalid={emailInvalid || undefined}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>
              <ReasonField id="demo-reason" value={demoReason} onChange={setDemoReason} />
            </div>
            {emailInvalid ? (
              <p className="note" role="alert">
                Enter an email address with a name, an @ sign, and a domain.
              </p>
            ) : null}
            <div className="actions">
              <button
                type="submit"
                className="primary"
                disabled={!demoReady || busy === "demographics"}
                aria-busy={busy === "demographics"}
              >
                Save name and email
              </button>
            </div>
          </form>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!reasonOk(loginReason)) return;
              void run("login", async () => {
                const disabled = !person.loginDisabled;
                await setLoginDisabled(sessionToken, person.uin, {
                  disabled,
                  reason: loginReason.trim(),
                });
                setPerson({ ...person, loginDisabled: disabled });
                setLoginReason("");
              });
            }}
          >
            <h2>Login</h2>
            <div className="stack">
              <ReasonField id="login-reason" value={loginReason} onChange={setLoginReason} />
            </div>
            <div className="actions">
              <button
                type="submit"
                className="primary"
                disabled={!reasonOk(loginReason) || busy === "login"}
                aria-busy={busy === "login"}
              >
                {person.loginDisabled ? "Turn login on" : "Turn login off"}
              </button>
            </div>
          </form>

          <form
            onSubmit={(event) => {
              event.preventDefault();
            }}
          >
            <h2>ID lock</h2>
            <div className="stack">
              <ReasonField id="lock-reason" value={lockReason} onChange={setLockReason} />
            </div>
            <div className="actions">
              <button
                type="button"
                className="primary"
                disabled={!reasonOk(lockReason) || busy === "lock" || busy === "unlock"}
                aria-busy={busy === "lock"}
                onClick={() =>
                  void run("lock", async () => {
                    const saved = await setCitizenLock(sessionToken, person.uin, {
                      locked: true,
                      reason: lockReason.trim(),
                    });
                    setPerson({ ...person, locked: saved.locked });
                    setLockReason("");
                  })
                }
              >
                Lock ID
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!reasonOk(lockReason) || busy === "lock" || busy === "unlock"}
                aria-busy={busy === "unlock"}
                onClick={() =>
                  void run("unlock", async () => {
                    const saved = await setCitizenLock(sessionToken, person.uin, {
                      locked: false,
                      reason: lockReason.trim(),
                    });
                    setPerson({ ...person, locked: saved.locked });
                    setLockReason("");
                  })
                }
              >
                Unlock ID
              </button>
            </div>
          </form>
          </>
          ) : null}

          {canManage ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!reasonOk(faceReason)) return;
                void run("face", async () => {
                  await deleteSavedFace(sessionToken, person.uin, faceReason.trim());
                  setFaceReason("");
                  setFaceNote("The saved face was removed.");
                });
              }}
            >
              <h2>Remove saved face</h2>
              {faceNote ? <p className="callout">{faceNote}</p> : null}
              <div className="stack">
                <ReasonField id="face-reason" value={faceReason} onChange={setFaceReason} />
              </div>
              <div className="actions">
                <button
                  type="submit"
                  className="secondary"
                  disabled={!reasonOk(faceReason) || busy === "face"}
                  aria-busy={busy === "face"}
                >
                  Remove saved face
                </button>
              </div>
            </form>
          ) : null}
        </section>
      ) : null}

      <section>
        <h2>Activity log</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const date = auditDate.trim();
            if (date !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
            void run("audit", async () => {
              setAuditRows(
                await searchAudit(sessionToken, {
                  uin: auditUin,
                  appCode: auditApp,
                  sessionId: auditSession,
                  date,
                }),
              );
              setAuditSearched(true);
            });
          }}
        >
          <div className="stack">
            <label htmlFor="audit-uin">
              UIN
              <input id="audit-uin" value={auditUin} onChange={(event) => setAuditUin(event.target.value)} />
            </label>
            <label htmlFor="audit-app">
              Application code
              <input id="audit-app" value={auditApp} onChange={(event) => setAuditApp(event.target.value)} />
            </label>
            <label htmlFor="audit-session">
              Session id
              <input
                id="audit-session"
                value={auditSession}
                spellCheck={false}
                onChange={(event) => setAuditSession(event.target.value)}
              />
            </label>
            <label htmlFor="audit-date">
              Date (YYYY-MM-DD)
              <input
                id="audit-date"
                type="date"
                value={auditDate}
                onChange={(event) => setAuditDate(event.target.value)}
              />
            </label>
          </div>
          <div className="actions">
            <button type="submit" className="primary" disabled={busy === "audit"} aria-busy={busy === "audit"}>
              Search
            </button>
          </div>
        </form>
        {auditSearched && auditRows.length === 0 ? <p>No activity matched that search.</p> : null}
        {auditRows.length > 0 ? (
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Event</th>
                  <th scope="col">Result</th>
                  <th scope="col">UIN</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Note</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {auditRows.map((row, index) => (
                  <tr key={row.eventId ?? row.checkId ?? `${row.uin ?? "row"}-${row.when ?? index}`}>
                    <td>{formatWhen(row.when)}</td>
                    <td>{row.event || row.kind || ""}</td>
                    <td>{row.result ?? ""}</td>
                    <td className="uin">{row.uin ?? ""}</td>
                    <td>{row.reasonCode ?? ""}</td>
                    <td>{row.officerText || row.message || ""}</td>
                    <td>{row.source || row.network || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section>
        <h2>Reports</h2>
        {!reportsLoaded ? (
          <p className="status" role="status">
            Loading reports…
          </p>
        ) : reports.length === 0 ? (
          <p>No reports.</p>
        ) : (
          <ul className="pick-list">
            {reports.map((report) => {
              const reason = reportReasons[report.checkId] ?? "";
              const openBusy = busy === `report-open-${report.checkId}`;
              const checkBusy = busy === `report-check-${report.checkId}`;
              return (
                <li key={report.checkId}>
                  <div className="facts">
                    <p>
                      <strong>When</strong> <span>{formatWhen(report.when)}</span>
                    </p>
                    {report.uin ? (
                      <p>
                        <strong>UIN</strong> <span className="uin">{report.uin}</span>
                      </p>
                    ) : null}
                    {report.event ? (
                      <p>
                        <strong>Event</strong> <span>{report.event}</span>
                      </p>
                    ) : null}
                    {report.result ? (
                      <p>
                        <strong>Result</strong> <span>{report.result}</span>
                      </p>
                    ) : null}
                    {report.message ? (
                      <p>
                        <strong>Message</strong> <span>{report.message}</span>
                      </p>
                    ) : null}
                    {report.status ? (
                      <p>
                        <strong>Status</strong> <span>{report.status}</span>
                      </p>
                    ) : null}
                  </div>
                  {reportNotes[report.checkId] ? <p className="callout">{reportNotes[report.checkId]}</p> : null}
                  <div className="actions">
                    <button
                      type="button"
                      className="secondary"
                      disabled={openBusy || checkBusy}
                      aria-busy={openBusy}
                      onClick={() =>
                        void run(`report-open-${report.checkId}`, async () => {
                          const opened = await openReport(sessionToken, report.checkId);
                          setReportNotes((current) => ({
                            ...current,
                            [report.checkId]: opened.status ?? "Opened.",
                          }));
                          setReportsVersion((current) => current + 1);
                        })
                      }
                    >
                      Open
                    </button>
                  </div>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      if (!reasonOk(reason)) return;
                      void run(`report-check-${report.checkId}`, async () => {
                        const checked = await markReportChecked(sessionToken, report.checkId, reason.trim());
                        setReportReasons((current) => ({ ...current, [report.checkId]: "" }));
                        setReportNotes((current) => ({
                          ...current,
                          [report.checkId]: checked.status ?? "Marked checked.",
                        }));
                        setReportsVersion((current) => current + 1);
                      });
                    }}
                  >
                    <div className="stack">
                      <ReasonField
                        id={`report-reason-${report.checkId}`}
                        value={reason}
                        onChange={(value) =>
                          setReportReasons((current) => ({ ...current, [report.checkId]: value }))
                        }
                      />
                    </div>
                    <div className="actions">
                      <button
                        type="submit"
                        className="primary"
                        disabled={!reasonOk(reason) || openBusy || checkBusy}
                        aria-busy={checkBusy}
                      >
                        Mark checked
                      </button>
                    </div>
                  </form>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {canManage ? (
        <section>
          <h2>Staff</h2>
          {issuedToken ? (
            <div className="panel">
              <strong>New staff token</strong>
              <p>Copy this token now. It is shown once.</p>
              <div className="uin-row">
                <p className="token-value">{issuedToken}</p>
                <CopyValue value={issuedToken} />
              </div>
            </div>
          ) : null}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!addReady) return;
              void run("add-staff", async () => {
                setIssuedToken(null);
                const created = await addStaff(sessionToken, {
                  name: staffName.trim(),
                  email: staffEmail.trim(),
                  role: staffRole,
                  reason: staffReason.trim(),
                });
                setIssuedToken(created.token);
                setStaffName("");
                setStaffEmail("");
                setStaffRolePick("officer");
                setStaffReason("");
                setListsVersion((current) => current + 1);
              });
            }}
          >
            <div className="stack">
              <label htmlFor="staff-name">
                Name
                <input id="staff-name" value={staffName} onChange={(event) => setStaffName(event.target.value)} />
              </label>
              <label htmlFor="staff-email">
                Email
                <input
                  id="staff-email"
                  type="email"
                  value={staffEmail}
                  aria-invalid={staffEmailInvalid || undefined}
                  onChange={(event) => setStaffEmail(event.target.value)}
                />
              </label>
              <label htmlFor="staff-role">
                Role
                <select
                  id="staff-role"
                  value={staffRole}
                  onChange={(event) => setStaffRolePick(event.target.value === "admin" ? "admin" : "officer")}
                >
                  <option value="officer">officer</option>
                  <option value="admin">admin</option>
                </select>
              </label>
              <ReasonField id="staff-add-reason" value={staffReason} onChange={setStaffReason} />
            </div>
            {staffEmailInvalid ? (
              <p className="note" role="alert">
                Enter an email address with a name, an @ sign, and a domain.
              </p>
            ) : null}
            <div className="actions">
              <button type="submit" className="primary" disabled={!addReady} aria-busy={busy === "add-staff"}>
                Add staff
              </button>
            </div>
          </form>

          {!listsLoaded ? (
            <p className="status" role="status">
              Loading staff…
            </p>
          ) : staff.length === 0 ? (
            <p>No staff yet.</p>
          ) : (
            <ul className="pick-list">
              {staff.map((member) => {
                const rowReason = rowReasons[member.id] ?? "";
                const nextRole = rowRoles[member.id] ?? (member.role === "admin" ? "admin" : "officer");
                const rowBusy = busy === `staff-${member.id}`;
                return (
                  <li key={member.id}>
                    <p>
                      <strong>{member.name || "No name"}</strong>
                    </p>
                    <p>{member.email}</p>
                    <p>Role: {member.role}</p>
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                      }}
                    >
                      <div className="stack">
                        <ReasonField
                          id={`staff-reason-${member.id}`}
                          value={rowReason}
                          onChange={(value) => setRowReasons((current) => ({ ...current, [member.id]: value }))}
                        />
                        <label htmlFor={`staff-role-${member.id}`}>
                          Role
                          <select
                            id={`staff-role-${member.id}`}
                            value={nextRole}
                            onChange={(event) =>
                              setRowRoles((current) => ({
                                ...current,
                                [member.id]: event.target.value === "admin" ? "admin" : "officer",
                              }))
                            }
                          >
                            <option value="officer">officer</option>
                            <option value="admin">admin</option>
                          </select>
                        </label>
                      </div>
                      <div className="actions">
                        <button
                          type="button"
                          className="secondary"
                          disabled={!reasonOk(rowReason) || rowBusy || nextRole === member.role}
                          aria-busy={rowBusy}
                          onClick={() =>
                            void run(`staff-${member.id}`, async () => {
                              await setStaffRole(sessionToken, member.id, {
                                role: nextRole,
                                reason: rowReason.trim(),
                              });
                              setRowReasons((current) => ({ ...current, [member.id]: "" }));
                              setListsVersion((current) => current + 1);
                            })
                          }
                        >
                          Save role
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={!reasonOk(rowReason) || rowBusy}
                          aria-busy={rowBusy}
                          onClick={() =>
                            void run(`staff-${member.id}`, async () => {
                              await removeStaff(sessionToken, member.id, rowReason.trim());
                              setRowReasons((current) => ({ ...current, [member.id]: "" }));
                              setListsVersion((current) => current + 1);
                            })
                          }
                        >
                          Remove
                        </button>
                      </div>
                    </form>
                  </li>
                );
              })}
            </ul>
          )}

          <h2>All checks</h2>
          {!listsLoaded ? (
            <p className="status" role="status">
              Loading checks…
            </p>
          ) : allChecks.length === 0 ? (
            <p>No checks yet.</p>
          ) : (
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">UIN</th>
                    <th scope="col">When</th>
                    <th scope="col">Result</th>
                    <th scope="col">Reason</th>
                    <th scope="col">Network</th>
                    <th scope="col">Person</th>
                  </tr>
                </thead>
                <tbody>
                  {allChecks.map((check, index) => (
                    <tr key={check.checkId ?? `${check.uin ?? "uin"}-${check.when ?? index}`}>
                      <td className="uin">{check.uin ?? ""}</td>
                      <td>{formatWhen(check.when)}</td>
                      <td>{check.result ?? ""}</td>
                      <td>{check.reasonCode ?? ""}</td>
                      <td>{check.network ?? ""}</td>
                      <td>
                        {check.uin ? (
                          <button type="button" className="quiet" onClick={() => void openPerson(check.uin ?? "")}>
                            Open
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      <div className="actions">
        <button type="button" className="quiet" onClick={signOut}>
          Sign out
        </button>
      </div>
    </Frame>
  );
}
