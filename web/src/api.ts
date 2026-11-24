export const FACE_ENGINE = "face-api-128";
export const FACE_MATCH_THRESHOLD = 0.5;

export type FacePurpose = "enroll" | "check";

export type FaceChallenge = {
  challengeId: string;
  purpose: FacePurpose;
  expiresInSeconds: number;
  requiredBlinks: number;
  sectors: string[];
};

export type LivenessReport = {
  challengeId: string;
  engine: typeof FACE_ENGINE;
  blinkCount: number;
  sweepYaws: number[];
};

export type EnrollResult = {
  status: string;
  uin: string;
  recordStatus: string;
  faceEngine: string;
  livenessSource: string;
  templateCount: number;
  message: string;
  emailSent: boolean;
  emailStatus: string;
  activityToken?: string | null;
};

export type VerifyResult = {
  status: string;
  verified: boolean;
  isFaceMatch: boolean;
  livenessPassed: boolean;
  compared: boolean;
  euclideanDistance: number | null;
  threshold: number | null;
  matchScore: number | null;
  message: string | null;
  livenessSource: string | null;
  jwtToken: null;
  activityToken?: string | null;
};

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type ErrorItem = { loc?: Array<string | number>; msg?: string };
type ErrorBody = { detail?: string | ErrorItem[] };

function formatErrorItem(item: ErrorItem): string | null {
  if (!item.msg) return null;
  const field = (item.loc ?? []).filter((part) => part !== "body").join(".");
  return field ? `${field}: ${item.msg}` : item.msg;
}

async function readError(response: Response): Promise<ApiError> {
  let message = response.statusText || `Request failed (${response.status})`;
  try {
    const { detail } = (await response.json()) as ErrorBody;
    if (typeof detail === "string" && detail) message = detail;
    else if (Array.isArray(detail)) {
      const parts = detail.map(formatErrorItem).filter((part): part is string => Boolean(part));
      if (parts.length) message = parts.join("; ");
    }
  } catch {
    // keep the status text
  }
  return new ApiError(response.status, message);
}

async function requestJson<T>(
  method: string,
  url: string,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

async function postJson<T>(url: string, body: unknown, headers?: Record<string, string>): Promise<T> {
  return requestJson<T>("POST", url, body, headers);
}

function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export const ACTIVITY_TOKEN_KEY = "register-id-activity";
export const DESK_TOKEN_KEY = "register-id-desk-token";

export function saveActivityToken(token: string | null | undefined) {
  if (typeof token !== "string" || token.trim() === "") return;
  sessionStorage.setItem(ACTIVITY_TOKEN_KEY, token);
}

export function activityToken(): string | null {
  try {
    const value = sessionStorage.getItem(ACTIVITY_TOKEN_KEY);
    return value && value.trim() ? value : null;
  } catch {
    return null;
  }
}

/** Fire-and-forget. Network and HTTP failures are ignored so the person can continue. */
export function reportAttempt(input: { kind: string; reasonCode: string; detail?: string }): void {
  const payload: { kind: string; reasonCode: string; detail?: string } = {
    kind: input.kind,
    reasonCode: input.reasonCode,
  };
  if (input.detail) payload.detail = input.detail;
  void fetch("/api/attempts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => undefined);
}

/** Element-wise mean of the scan's descriptors, sent as the single probe. */
export function meanDescriptor(descriptors: readonly number[][]): number[] {
  if (descriptors.length === 0) throw new Error("The scan has no face descriptors.");
  const mean = new Array<number>(descriptors[0].length).fill(0);
  for (const descriptor of descriptors) {
    for (let i = 0; i < mean.length; i++) mean[i] += descriptor[i] ?? 0;
  }
  return mean.map((sum) => sum / descriptors.length);
}

export function getFaceChallenge(purpose: FacePurpose) {
  return postJson<FaceChallenge>("/api/face/challenge", { purpose });
}

export async function issueEnrollTicket() {
  const response = await fetch("/api/enroll/ticket", { method: "POST" });
  if (!response.ok) throw await readError(response);
  const body = (await response.json()) as { ticket: string };
  return body.ticket;
}

export async function enrollCitizen(input: {
  fullName: string;
  email: string;
  gender: string;
  dateOfBirth: string;
  faceImage: string;
  faceDescriptors: number[][];
  liveness: LivenessReport;
  emailIdCard?: boolean;
  idCardImage?: string;
  phone?: string;
  addressLine1?: string;
  addressLine2?: string;
  addressLine3?: string;
  region?: string;
  province?: string;
  city?: string;
  zone?: string;
  postalCode?: string;
}) {
  const ticket = await issueEnrollTicket();
  const emailIdCard = input.emailIdCard ?? false;
  return postJson<EnrollResult>(
    "/api/enroll",
    {
      fullName: input.fullName,
      email: input.email,
      gender: input.gender,
      dateOfBirth: input.dateOfBirth,
      phone: input.phone ?? "",
      addressLine1: input.addressLine1 ?? "",
      addressLine2: input.addressLine2 ?? "",
      addressLine3: input.addressLine3 ?? "",
      region: input.region ?? "",
      province: input.province ?? "",
      city: input.city ?? "",
      zone: input.zone ?? "",
      postalCode: input.postalCode ?? "",
      faceImage: input.faceImage,
      consent: {
        accepted: true,
        purpose: "Create a citizen ID and store the face image for this registration",
        acceptedAt: Date.now() / 1000,
        language: "eng",
      },
      faceDescriptors: input.faceDescriptors,
      liveness: input.liveness,
      emailIdCard,
      ...(emailIdCard && input.idCardImage ? { idCardImage: input.idCardImage } : {}),
    },
    { "X-Enroll-Ticket": ticket },
  );
}

export function verifyFace(input: { uin: string; probeDescriptor: number[]; liveness: LivenessReport }) {
  return postJson<VerifyResult>("/api/authenticate", input);
}

export type ApplicationReason = "no-camera" | "camera-quality";

export type ApplicationDraft = {
  code: string;
  expiresAt: number;
  expiresInSeconds: number;
};

export function createApplication(input: {
  fullName: string;
  gender: string;
  dateOfBirth: string;
  email: string;
  researchOptIn: boolean;
  reason: ApplicationReason;
  consent: {
    accepted: true;
    purpose: string;
    acceptedAt: number;
    language: "eng" | "tha";
  };
}) {
  return postJson<ApplicationDraft>("/api/applications", input);
}

export type CitizenSummary = {
  uin: string;
  fullName: string;
  email: string | null;
};

export type CitizenRecord = {
  uin: string;
  fullName: string;
  email: string | null;
  loginDisabled: boolean;
  locked?: boolean;
};

export type IdentityCheck = {
  checkId?: string;
  eventId?: string;
  uin?: string;
  when?: number;
  event?: string;
  kind?: string;
  result?: string;
  message?: string;
  device?: string;
  livenessPassed?: boolean;
  matchPassed?: boolean;
  livenessScore?: number | null;
  matchScore?: number | null;
  network?: string | null;
  browser?: string | null;
  reasonCode?: string | null;
  officerText?: string;
  source?: string;
};

export type AuditQuery = {
  uin?: string;
  appCode?: string;
  sessionId?: string;
  date?: string;
};

export type CitizenReport = {
  checkId: string;
  uin?: string;
  when?: number;
  event?: string;
  result?: string;
  message?: string;
  status?: string;
};

export type ReportAction = {
  checkId: string;
  status?: string;
};

export type LockState = {
  uin: string;
  locked: boolean;
};

export type StaffMember = {
  id: string;
  name: string;
  email: string;
  role: string;
};

export type StaffCreated = StaffMember & { token: string };

export type ActivityReport = {
  uin?: string;
  triesUsed?: number;
  askWasThisYou?: boolean;
  checks: IdentityCheck[];
  disputes: string[];
};

function readRows(body: unknown): unknown[] {
  if (Array.isArray(body)) return body;
  if (!body || typeof body !== "object") return [];
  const record = body as Record<string, unknown>;
  for (const key of ["staff", "members", "checks", "citizens", "results", "items", "events", "reports", "rows", "audit"]) {
    if (Array.isArray(record[key])) return record[key] as unknown[];
  }
  return [];
}

function readText(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function readWhen(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || value.trim() === "") return undefined;
  const text = value.trim();
  if (/^-?\d+(\.\d+)?$/.test(text)) {
    const numeric = Number(text);
    return Number.isFinite(numeric) ? numeric : undefined;
  }
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function readDevice(value: unknown): string | undefined {
  const text = readText(value);
  if (text) return text;
  if (!value || typeof value !== "object") return undefined;
  const row = value as Record<string, unknown>;
  return readText(row.rough) ?? readText(row.kind) ?? readText(row.type) ?? readText(row.class) ?? undefined;
}

function readLocked(row: Record<string, unknown>): boolean | undefined {
  if (typeof row.locked === "boolean") return row.locked;
  if (typeof row.idLocked === "boolean") return row.idLocked;
  return undefined;
}

function readScore(value: unknown): number | null | undefined {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return undefined;
}

function readBool(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function readCitizenSummary(value: unknown): CitizenSummary | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const uin = readText(row.uin);
  if (!uin) return null;
  return {
    uin,
    fullName: readText(row.fullName) ?? readText(row.name) ?? "",
    email: readText(row.email),
  };
}

function readCitizen(value: unknown): CitizenRecord | null {
  const summary = readCitizenSummary(value);
  if (!summary || !value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const locked = readLocked(row);
  return {
    ...summary,
    loginDisabled: row.loginDisabled === true,
    ...(locked !== undefined ? { locked } : {}),
  };
}

function readCheck(value: unknown): IdentityCheck | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const check: IdentityCheck = {};
  const checkId = readText(row.checkId);
  const eventId = readText(row.eventId);
  const uin = readText(row.uin);
  const result = readText(row.result);
  const event = readText(row.event);
  const kind = readText(row.kind);
  const message = readText(row.message) ?? readText(row.detail) ?? readText(row.reason);
  const device = readDevice(row.device);
  const network = readText(row.network);
  const browser = readText(row.browser);
  const reasonCode = readText(row.reasonCode);
  const officerText = readText(row.officerText);
  const source = readText(row.source) ?? readText(row.ip);
  const when = readWhen(row.time ?? row.timestamp ?? row.when);
  if (checkId) check.checkId = checkId;
  if (eventId) check.eventId = eventId;
  if (uin) check.uin = uin;
  if (when !== undefined) check.when = when;
  if (event) check.event = event;
  if (kind) check.kind = kind;
  if (result) check.result = result;
  if (message) check.message = message;
  if (device) check.device = device;
  const livenessPassed = readBool(row.livenessPassed);
  const matchPassed = readBool(row.matchPassed);
  if (livenessPassed !== undefined) check.livenessPassed = livenessPassed;
  if (matchPassed !== undefined) check.matchPassed = matchPassed;
  const livenessScore = readScore(row.livenessScore);
  const matchScore = readScore(row.matchScore);
  if (livenessScore !== undefined) check.livenessScore = livenessScore;
  if (matchScore !== undefined) check.matchScore = matchScore;
  if (network) check.network = network;
  if (browser) check.browser = browser;
  if (reasonCode) check.reasonCode = reasonCode;
  if (officerText) check.officerText = officerText;
  if (source) check.source = source;
  return check;
}

function readReport(value: unknown): CitizenReport | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const checkId = readText(row.checkId);
  if (!checkId) return null;
  const report: CitizenReport = { checkId };
  const uin = readText(row.uin);
  const event = readText(row.event) ?? readText(row.kind);
  const result = readText(row.result);
  const message = readText(row.message) ?? readText(row.detail) ?? readText(row.reason);
  const status = readText(row.status);
  const when = readWhen(row.time ?? row.timestamp ?? row.when);
  if (uin) report.uin = uin;
  if (when !== undefined) report.when = when;
  if (event) report.event = event;
  if (result) report.result = result;
  if (message) report.message = message;
  if (status) report.status = status;
  return report;
}

function readReportAction(checkId: string, body: unknown): ReportAction {
  const action: ReportAction = { checkId };
  if (body && typeof body === "object") {
    const status = readText((body as { status?: unknown }).status);
    if (status) action.status = status;
  }
  return action;
}

function readStaff(value: unknown): StaffMember | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const id = readText(row.id) ?? (typeof row.id === "number" ? String(row.id) : null);
  if (!id) return null;
  return {
    id,
    name: readText(row.name) ?? "",
    email: readText(row.email) ?? "",
    role: readText(row.role) ?? "",
  };
}

function readDisputes(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const ids: string[] = [];
  for (const item of value) {
    if (typeof item === "string" && item.trim() !== "") ids.push(item);
    else if (item && typeof item === "object") {
      const checkId = readText((item as { checkId?: unknown }).checkId);
      if (checkId) ids.push(checkId);
    }
  }
  return ids;
}

export function deskSession(token: string) {
  return requestJson<{ role?: unknown }>("GET", "/api/desk/session", undefined, bearer(token)).then((body) => {
    const role = body && typeof body.role === "string" ? body.role.trim() : "";
    if (!role) throw new ApiError(502, "The desk session did not include a role.");
    return { role };
  });
}

export async function searchCitizens(token: string, query: string) {
  const body = await requestJson<unknown>(
    "GET",
    `/api/citizens?q=${encodeURIComponent(query)}`,
    undefined,
    bearer(token),
  );
  return readRows(body).map(readCitizenSummary).filter((row): row is CitizenSummary => row !== null);
}

export async function getCitizen(token: string, uin: string) {
  const body = await requestJson<unknown>(
    "GET",
    `/api/citizens/${encodeURIComponent(uin)}`,
    undefined,
    bearer(token),
  );
  const citizen = readCitizen(body);
  if (!citizen) throw new ApiError(502, "The person record could not be read.");
  return citizen;
}

export async function getCitizenChecks(token: string, uin: string) {
  const body = await requestJson<unknown>(
    "GET",
    `/api/citizens/${encodeURIComponent(uin)}/checks`,
    undefined,
    bearer(token),
  );
  return readRows(body).map(readCheck).filter((row): row is IdentityCheck => row !== null);
}

export function updateDemographics(
  token: string,
  uin: string,
  input: { fullName: string; email: string; reason: string },
) {
  return postJson<{ uin?: string; fullName?: string; email?: string }>(
    `/api/citizens/${encodeURIComponent(uin)}/demographics`,
    input,
    bearer(token),
  );
}

export function setLoginDisabled(token: string, uin: string, input: { disabled: boolean; reason: string }) {
  return postJson<{ uin?: string; loginDisabled?: boolean }>(
    `/api/citizens/${encodeURIComponent(uin)}/login-disabled`,
    input,
    bearer(token),
  );
}

export async function setCitizenLock(
  token: string,
  uin: string,
  input: { locked: boolean; reason: string },
): Promise<LockState> {
  const body = await postJson<unknown>(`/api/citizens/${encodeURIComponent(uin)}/lock`, input, bearer(token));
  if (!body || typeof body !== "object" || typeof (body as { locked?: unknown }).locked !== "boolean") {
    throw new ApiError(502, "The lock state was not returned.");
  }
  const row = body as { uin?: unknown; locked: boolean };
  return { uin: readText(row.uin) ?? uin, locked: row.locked };
}

export function deleteSavedFace(token: string, uin: string, reason: string) {
  return postJson<{ uin?: string }>(
    `/api/citizens/${encodeURIComponent(uin)}/delete-face`,
    { reason },
    bearer(token),
  );
}

export async function listStaff(token: string) {
  const body = await requestJson<unknown>("GET", "/api/staff", undefined, bearer(token));
  return readRows(body).map(readStaff).filter((row): row is StaffMember => row !== null);
}

export async function addStaff(
  token: string,
  input: { name: string; email: string; role: "officer" | "admin"; reason: string },
) {
  const body = await postJson<unknown>("/api/staff", input, bearer(token));
  const member = readStaff(body);
  const issued =
    body && typeof body === "object" ? readText((body as { token?: unknown }).token) : null;
  if (!member || !issued) throw new ApiError(502, "The staff token was not returned.");
  return { ...member, token: issued };
}

export function removeStaff(token: string, id: string, reason: string) {
  return requestJson<unknown>(
    "DELETE",
    `/api/staff/${encodeURIComponent(id)}`,
    { reason },
    bearer(token),
  );
}

export function setStaffRole(token: string, id: string, input: { role: "officer" | "admin"; reason: string }) {
  return postJson<unknown>(`/api/staff/${encodeURIComponent(id)}/role`, input, bearer(token));
}

export async function listChecks(token: string) {
  const body = await requestJson<unknown>("GET", "/api/checks", undefined, bearer(token));
  return readRows(body).map(readCheck).filter((row): row is IdentityCheck => row !== null);
}

export async function searchAudit(token: string, query: AuditQuery) {
  const params = new URLSearchParams();
  const uin = query.uin?.trim() ?? "";
  const appCode = query.appCode?.trim() ?? "";
  const sessionId = query.sessionId?.trim() ?? "";
  const date = query.date?.trim() ?? "";
  if (uin) params.set("uin", uin);
  if (appCode) params.set("appCode", appCode);
  if (sessionId) params.set("sessionId", sessionId);
  if (date) params.set("date", date);
  const search = params.toString();
  const body = await requestJson<unknown>(
    "GET",
    `/api/audit${search ? `?${search}` : ""}`,
    undefined,
    bearer(token),
  );
  return readRows(body).map(readCheck).filter((row): row is IdentityCheck => row !== null);
}

export async function listReports(token: string) {
  const body = await requestJson<unknown>("GET", "/api/reports", undefined, bearer(token));
  return readRows(body).map(readReport).filter((row): row is CitizenReport => row !== null);
}

export async function openReport(token: string, checkId: string) {
  const body = await requestJson<unknown>(
    "POST",
    `/api/reports/${encodeURIComponent(checkId)}/open`,
    undefined,
    bearer(token),
  );
  return readReportAction(checkId, body);
}

export async function markReportChecked(token: string, checkId: string, reason: string) {
  const body = await postJson<unknown>(
    `/api/reports/${encodeURIComponent(checkId)}/checked`,
    { reason },
    bearer(token),
  );
  return readReportAction(checkId, body);
}

export async function myActivity(token: string): Promise<ActivityReport> {
  const body = await requestJson<unknown>("GET", "/api/me/activity", undefined, bearer(token));
  if (!body || typeof body !== "object") return { checks: [], disputes: [] };
  const record = body as Record<string, unknown>;
  const checks = (Array.isArray(record.checks) ? record.checks : readRows(body))
    .map(readCheck)
    .filter((row): row is IdentityCheck => row !== null);
  const triesUsed =
    typeof record.triesUsed === "number" && Number.isFinite(record.triesUsed) ? record.triesUsed : undefined;
  const uin = readText(record.uin) ?? undefined;
  return {
    ...(uin ? { uin } : {}),
    ...(triesUsed !== undefined ? { triesUsed } : {}),
    askWasThisYou: record.askWasThisYou === true,
    checks,
    disputes: readDisputes(record.disputes),
  };
}

export function reportNotMe(token: string, checkId: string, detail: string) {
  const trimmed = detail.trim();
  return postJson<unknown>(
    `/api/me/activity/${encodeURIComponent(checkId)}/not-me`,
    trimmed ? { detail: trimmed } : {},
    bearer(token),
  );
}
