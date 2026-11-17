export type EnrollResult = {
  status: string;
  uin: string;
  cbeffGenerated: boolean;
  recordStatus?: string;
};

export type AuthResult = {
  status: string;
  verified: boolean;
  isFaceMatch: boolean;
  livenessPassed: boolean;
  jwtToken: null;
  message: string | null;
  sweepAccepted: boolean;
};

async function readError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function issueUin() {
  const response = await fetch("/api/idgenerator/uin");
  if (!response.ok) throw new Error(await readError(response));
  const body = (await response.json()) as { uin: string };
  return body.uin;
}

export async function enrollCitizen(input: {
  uin: string;
  fullName: string;
  email: string;
  faceImage: string;
}) {
  const response = await fetch("/api/enroll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
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
    }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as EnrollResult;
}

export async function checkFace(input: { uin: string; liveImage: string }) {
  const response = await fetch("/api/authenticate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      uin: input.uin,
      liveImage: input.liveImage,
      livenessScore: 0,
      livenessPassed: false,
    }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as AuthResult;
}
