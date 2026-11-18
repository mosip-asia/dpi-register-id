import jsQR from "jsqr";
import { toDataURL } from "qrcode";

/** A registration number is 8–16 digits, with optional hyphen groups. */
const UIN_BODY = /^[\d-]{8,22}$/;

export function uinFromQrText(raw: string): string | null {
  const compact = raw.trim().replace(/\s+/g, "");
  const candidates = [compact, ...(compact.match(/\d[\d-]{6,20}\d/g) ?? [])];
  for (const candidate of candidates) {
    if (!UIN_BODY.test(candidate)) continue;
    const digits = candidate.replace(/-/g, "");
    if (/^\d{8,16}$/.test(digits)) return candidate;
  }
  return null;
}

export function uinQrDataUrl(uin: string, width = 280): Promise<string> {
  return toDataURL(uin, {
    errorCorrectionLevel: "H",
    margin: 2,
    width,
    color: { dark: "#1a1a1a", light: "#ffffff" },
  });
}

export async function uinFromQrFile(file: File): Promise<string | null> {
  const bitmap = await createImageBitmap(file);
  try {
    const maxEdge = 1200;
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(bitmap, 0, 0, width, height);
    const image = context.getImageData(0, 0, width, height);
    const code = jsQR(image.data, width, height, { inversionAttempts: "attemptBoth" });
    return code ? uinFromQrText(code.data) : null;
  } finally {
    bitmap.close();
  }
}
