// Pure liveness logic ported from the /lab page (src/project/web/templates/index.html).
// Inputs are the 68 face-api landmark positions in raw (unmirrored) video pixels.

export interface Point {
  x: number;
  y: number;
}

export const SECTORS = ["far-left", "left", "front", "right", "far-right"] as const;
export type Sector = (typeof SECTORS)[number];

export const SECTOR_LABELS: Record<Sector, string> = {
  "far-left": "Far left",
  left: "Left",
  front: "Front",
  right: "Right",
  "far-right": "Far right",
};

export const SECTOR_CENTERS: Record<Sector, number> = {
  "far-left": -0.6,
  left: -0.29,
  front: 0,
  right: 0.29,
  "far-right": 0.6,
};

// A sample is only recorded when it falls inside its sector's band. Neighbouring
// bands are at least 0.1 apart, so recorded yaws always beat SWEEP_MIN_STEP.
export const SECTOR_BANDS: Record<Sector, readonly [number, number]> = {
  "far-left": [-1.2, -0.44],
  left: [-0.34, -0.2],
  front: [-0.1, 0.1],
  right: [0.2, 0.34],
  "far-right": [0.44, 1.2],
};

export const SWEEP_MIN_STEP = 0.08;
export const SWEEP_MIN_SPAN = 0.5;

const dist = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

function centroid(points: readonly Point[]): Point {
  let x = 0;
  let y = 0;
  for (const p of points) {
    x += p.x;
    y += p.y;
  }
  const n = points.length || 1;
  return { x: x / n, y: y / n };
}

const jawOutline = (points: readonly Point[]) => points.slice(0, 17);
const nose = (points: readonly Point[]) => points.slice(27, 36);
const leftEye = (points: readonly Point[]) => points.slice(36, 42);
const rightEye = (points: readonly Point[]) => points.slice(42, 48);

/**
 * Head yaw from the nose tip's position between the jaw ends, in -1.2..1.2.
 * Negative is the subject's own left. On an unmirrored front camera the
 * subject's left is image right, so this must be fed raw video pixels.
 */
export function estimateYaw(points: readonly Point[]): number {
  const jaw = jawOutline(points);
  const noseLine = nose(points);
  const tip = noseLine[3] ?? noseLine[Math.floor(noseLine.length / 2)];
  const imageLeft = jaw[0];
  const imageRight = jaw[jaw.length - 1];
  if (!tip || !imageLeft || !imageRight) return 0;
  const leftDist = dist(tip, imageLeft);
  const rightDist = dist(tip, imageRight);
  const span = leftDist + rightDist || 1;
  const yaw = (rightDist - leftDist) / span;
  return Math.max(-1.2, Math.min(1.2, yaw));
}

export function sectorForYaw(yaw: number): Sector {
  if (yaw <= -0.42) return "far-left";
  if (yaw <= -0.16) return "left";
  if (yaw < 0.16) return "front";
  if (yaw < 0.42) return "right";
  return "far-right";
}

/** Eye aspect ratio for one 6-point eye contour. */
export function calculateEAR(eye: readonly Point[]): number {
  if (eye.length < 6) return 0;
  const h = dist(eye[0], eye[3]);
  if (h === 0) return 0;
  return (dist(eye[1], eye[5]) + dist(eye[2], eye[4])) / (2 * h);
}

export interface EyeMeasure {
  leftEar: number;
  rightEar: number;
  avgEar: number;
  earGap: number;
  /** Narrower eye width over the wider one. */
  widthRatio: number;
  /** Narrower eye width over the inter-ocular distance. */
  minWidthRatio: number;
  /** Nose drop below the eye line over eye-to-chin height; grows when looking down. */
  pitch: number;
  yaw: number;
}

export function measureEyes(points: readonly Point[]): EyeMeasure {
  const left = leftEye(points);
  const right = rightEye(points);
  const noseLine = nose(points);
  const jaw = jawOutline(points);
  const leftEar = calculateEAR(left);
  const rightEar = calculateEAR(right);
  const leftWidth = left.length >= 4 ? dist(left[0], left[3]) : 0;
  const rightWidth = right.length >= 4 ? dist(right[0], right[3]) : 0;
  const leftCenter = centroid(left);
  const rightCenter = centroid(right);
  const eyeMid = { x: (leftCenter.x + rightCenter.x) / 2, y: (leftCenter.y + rightCenter.y) / 2 };
  const noseTip = noseLine[Math.floor(noseLine.length / 2)] ?? noseLine[0] ?? eyeMid;
  const chin = jaw[8] ?? jaw[jaw.length - 1] ?? eyeMid;
  const faceH = Math.max(1, dist(eyeMid, chin));
  const iod = Math.max(1, dist(leftCenter, rightCenter));
  const narrower = Math.min(leftWidth, rightWidth);
  return {
    leftEar,
    rightEar,
    avgEar: (leftEar + rightEar) / 2,
    earGap: Math.abs(leftEar - rightEar),
    widthRatio: narrower / Math.max(leftWidth, rightWidth, 0.001),
    minWidthRatio: narrower / iod,
    pitch: (noseTip.y - eyeMid.y) / faceH,
    yaw: estimateYaw(points),
  };
}

/**
 * Why the eyes cannot be trusted for a blink, or null when both are usable.
 * Looking down or losing an eye collapses one contour; a real blink keeps both similar.
 */
export function eyeVisibility(eyes: EyeMeasure): string | null {
  if (eyes.earGap > 0.12) return "asymmetric eyes";
  if (eyes.widthRatio < 0.65) return "one eye collapsed";
  if (eyes.minWidthRatio < 0.18) return "eyes not visible";
  if (Math.abs(eyes.yaw) > 0.34) return "head turned too far";
  return null;
}

export interface BlinkUpdate {
  blinked: boolean;
  eyesClosed: boolean;
  reject: string | null;
  closeThreshold: number;
}

export interface BlinkTracker {
  readonly count: number;
  update(eyes: EyeMeasure, nowMs: number): BlinkUpdate;
  /** Drop a closure in progress, e.g. when the face is lost. */
  interrupt(): void;
  reset(): void;
}

const BLINK_MIN_MS = 40;
const BLINK_MAX_MS = 700;
const BLINK_DEBOUNCE_MS = 280;
const PITCH_DRIFT = 0.06;
const YAW_DRIFT = 0.12;

/** Adaptive-EAR blink counter: both eyes must close and reopen with a steady head. */
export function createBlinkTracker(): BlinkTracker {
  let count = 0;
  let baseline = 0;
  let pitchBaseline = 0;
  let closed = false;
  let closedSince = 0;
  let closePitch = 0;
  let closeYaw = 0;
  let lastBlinkAt = Number.NEGATIVE_INFINITY;
  let closeThreshold = 0;

  const result = (blinked: boolean, reject: string | null): BlinkUpdate => ({
    blinked,
    eyesClosed: closed,
    reject,
    closeThreshold,
  });

  return {
    get count() {
      return count;
    },
    update(eyes, now) {
      const reject = eyeVisibility(eyes);
      if (reject) {
        closed = false;
        return result(false, reject);
      }

      if (!closed) {
        if (baseline === 0) {
          baseline = eyes.avgEar;
          pitchBaseline = eyes.pitch;
        } else {
          baseline = baseline * 0.85 + eyes.avgEar * 0.15;
          pitchBaseline = pitchBaseline * 0.9 + eyes.pitch * 0.1;
        }
      }

      closeThreshold = Math.max(0.12, Math.min(0.24, baseline * 0.72));
      const openThreshold = closeThreshold + 0.04;
      const bothClosed = eyes.leftEar < closeThreshold && eyes.rightEar < closeThreshold;
      const bothOpen = eyes.leftEar >= openThreshold && eyes.rightEar >= openThreshold;
      const pitchDrift = Math.abs(eyes.pitch - (closed ? closePitch : pitchBaseline));

      if (!closed && bothClosed) {
        if (pitchDrift > PITCH_DRIFT) return result(false, "pitch changed (look down)");
        closed = true;
        closedSince = now;
        closePitch = eyes.pitch;
        closeYaw = eyes.yaw;
        return result(false, null);
      }

      if (closed) {
        const yawDrift = Math.abs(eyes.yaw - closeYaw);
        if (pitchDrift > PITCH_DRIFT || yawDrift > YAW_DRIFT) {
          closed = false;
          return result(false, pitchDrift > PITCH_DRIFT ? "pitch changed (look down)" : "head moved");
        }
        if (bothOpen) {
          const closedMs = now - closedSince;
          closed = false;
          if (closedMs < BLINK_MIN_MS || closedMs > BLINK_MAX_MS) {
            return result(false, `closed for ${Math.round(closedMs)}ms`);
          }
          if (now - lastBlinkAt < BLINK_DEBOUNCE_MS) return result(false, null);
          lastBlinkAt = now;
          count += 1;
          return result(true, null);
        }
      }

      return result(false, null);
    },
    interrupt() {
      closed = false;
    },
    reset() {
      count = 0;
      baseline = 0;
      pitchBaseline = 0;
      closed = false;
      closedSince = 0;
      closePitch = 0;
      closeYaw = 0;
      lastBlinkAt = Number.NEGATIVE_INFINITY;
      closeThreshold = 0;
    },
  };
}

export interface SweepTracker {
  readonly complete: boolean;
  /** Feed one yaw sample; returns the sector whose recorded sample changed, if any. */
  update(yaw: number): Sector | null;
  visited(): Sector[];
  /** Recorded yaws in SECTORS order, or null until every sector is visited. */
  sweepYaws(): number[] | null;
  /** Forget the pending sector streak, e.g. when the face leaves the oval. */
  interrupt(): void;
  reset(): void;
}

const SWEEP_STREAK = 2;

/** Head-sweep recorder keeping, per sector, the in-band sample closest to the sector center. */
export function createSweepTracker(): SweepTracker {
  let samples: Partial<Record<Sector, number>> = {};
  let pending: Sector | null = null;
  let streak = 0;

  const isComplete = () => SECTORS.every((sector) => samples[sector] !== undefined);

  return {
    get complete() {
      return isComplete();
    },
    update(yaw) {
      if (!Number.isFinite(yaw)) return null;
      const sector = sectorForYaw(yaw);
      if (pending === sector) streak += 1;
      else {
        pending = sector;
        streak = 1;
      }
      if (streak < SWEEP_STREAK) return null;

      const [low, high] = SECTOR_BANDS[sector];
      if (yaw < low || yaw > high) return null;
      const center = SECTOR_CENTERS[sector];
      const existing = samples[sector];
      if (existing !== undefined && Math.abs(existing - center) <= Math.abs(yaw - center)) return null;
      samples = { ...samples, [sector]: yaw };
      return sector;
    },
    visited() {
      return SECTORS.filter((sector) => samples[sector] !== undefined);
    },
    sweepYaws() {
      if (!isComplete()) return null;
      return SECTORS.map((sector) => samples[sector] as number);
    },
    interrupt() {
      pending = null;
      streak = 0;
    },
    reset() {
      samples = {};
      pending = null;
      streak = 0;
    },
  };
}

/** Same acceptance rule the server applies to sweepYaws. */
export function validateSweep(yaws: readonly number[]): boolean {
  if (yaws.length !== SECTORS.length || !yaws.every(Number.isFinite)) return false;
  for (let i = 1; i < yaws.length; i++) {
    if (yaws[i] - yaws[i - 1] < SWEEP_MIN_STEP) return false;
  }
  return yaws[yaws.length - 1] - yaws[0] >= SWEEP_MIN_SPAN;
}
