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

async function postJson<T>(
  url: string,
  body: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as T;
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

export async function issueUin() {
  const response = await fetch("/api/idgenerator/uin");
  if (!response.ok) throw await readError(response);
  const body = (await response.json()) as { uin: string };
  return body.uin;
}

export function enrollCitizen(input: {
  uin: string;
  fullName: string;
  email: string;
  faceImage: string;
  faceDescriptors: number[][];
  liveness: LivenessReport;
  emailIdCard?: boolean;
  idCardImage?: string;
}) {
  const emailIdCard = input.emailIdCard ?? false;
  return postJson<EnrollResult>("/api/enroll", {
    uin: input.uin,
    fullName: input.fullName,
    email: input.email,
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
  });
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
