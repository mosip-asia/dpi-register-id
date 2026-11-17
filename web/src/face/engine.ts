import type * as FaceApi from "@vladmandic/face-api";
import { eyeVisibility, measureEyes, type EyeMeasure } from "./liveness";

export const FACE_ENGINE = "face-api-128";
export const MODEL_URL = "/models";

type FaceApiModule = typeof FaceApi;
export type FaceInput = HTMLVideoElement | HTMLCanvasElement;

export interface NormalizedBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FaceSample {
  status: "none" | "many" | "one";
  faces: number;
  /** Detector confidence of the best face, 0 when none. */
  score: number;
  /** Face box as fractions of the raw video frame. */
  box: NormalizedBox | null;
  /** Face center inside the oval guide. */
  centered: boolean;
  /** Face width within the oval's size bounds. */
  sizeOk: boolean;
  /** Negative is the subject's own left (image right on an unmirrored camera). */
  yaw: number | null;
  ear: number;
  leftEar: number;
  rightEar: number;
  eyes: EyeMeasure | null;
  eyesUsable: boolean;
  descriptor?: number[];
}

export interface AnalyzeOptions {
  withDescriptor?: boolean;
}

export interface Oval {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

export class FaceModelError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "FaceModelError";
  }
}

const MIN_CONFIDENCE = 0.4;

let api: FaceApiModule | null = null;
let loading: Promise<{ backend: string }> | null = null;

// The bundled TFJS typings omit backend control, but the runtime has it.
interface TfBackendControl {
  setBackend(name: string): Promise<boolean>;
  ready(): Promise<void>;
}

async function selectBackend(faceapi: FaceApiModule): Promise<string> {
  const tf = faceapi.tf as unknown as TfBackendControl;
  // wasm is bundled too but needs separately hosted .wasm binaries.
  for (const name of ["webgl", "cpu"]) {
    try {
      if (await tf.setBackend(name)) {
        await tf.ready();
        return name;
      }
    } catch {
      // try the next backend
    }
  }
  throw new FaceModelError("No TensorFlow backend is available in this browser.");
}

/** Loads face-api and its weights once. Rejects with FaceModelError; a later call retries. */
export function loadFaceModels(): Promise<{ backend: string }> {
  if (!loading) {
    loading = (async () => {
      const faceapi = await import("@vladmandic/face-api");
      const backend = await selectBackend(faceapi);
      await Promise.all([
        faceapi.nets.ssdMobilenetv1.loadFromUri(MODEL_URL),
        faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
        faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
      ]);
      api = faceapi;
      return { backend };
    })().catch((err: unknown) => {
      loading = null;
      if (err instanceof FaceModelError) throw err;
      throw new FaceModelError("Face models failed to load.", { cause: err });
    });
  }
  return loading;
}

export function faceModelsReady(): boolean {
  return api !== null;
}

/**
 * Oval guide in frame pixels. Matches the lab oval on a 4:3 landscape frame
 * and scales with the shorter side so portrait and 16:9 frames stay sensible.
 */
export function ovalGeometry(width: number, height: number): Oval {
  const side = Math.min(width, height);
  return { cx: width / 2, cy: height * 0.46, rx: side * (0.22 * 4) / 3, ry: side * 0.36 };
}

function frameSize(input: FaceInput): { width: number; height: number } {
  if (input instanceof HTMLVideoElement) return { width: input.videoWidth, height: input.videoHeight };
  return { width: input.width, height: input.height };
}

const NO_FACE: FaceSample = {
  status: "none",
  faces: 0,
  score: 0,
  box: null,
  centered: false,
  sizeOk: false,
  yaw: null,
  ear: 0,
  leftEar: 0,
  rightEar: 0,
  eyes: null,
  eyesUsable: false,
};

/** Detects faces in one frame. Landmarks always; the 128-d descriptor only on request. */
export async function analyze(input: FaceInput, options: AnalyzeOptions = {}): Promise<FaceSample> {
  if (!api) throw new FaceModelError("Face models are not loaded.");
  const { width, height } = frameSize(input);
  if (!width || !height) return NO_FACE;

  const detect = api
    .detectAllFaces(input, new api.SsdMobilenetv1Options({ minConfidence: MIN_CONFIDENCE }))
    .withFaceLandmarks();
  const faces: Array<FaceApi.WithFaceLandmarks<FaceApi.WithFaceDetection<{}>> & { descriptor?: Float32Array }> =
    options.withDescriptor ? await detect.withFaceDescriptors() : await detect;

  const score = faces.reduce((best, face) => Math.max(best, face.detection.score), 0);
  if (faces.length !== 1) return { ...NO_FACE, status: faces.length ? "many" : "none", faces: faces.length, score };

  const face = faces[0];
  const { x, y, width: w, height: h } = face.detection.box;
  const oval = ovalGeometry(width, height);
  const fx = x + w / 2;
  const fy = y + h / 2;
  const centered = ((fx - oval.cx) / oval.rx) ** 2 + ((fy - oval.cy) / oval.ry) ** 2 <= 1;
  const sizeOk = w >= 0.55 * 2 * oval.rx && w <= 1.15 * 2 * oval.rx;
  const eyes = measureEyes(face.landmarks.positions);

  return {
    status: "one",
    faces: 1,
    score,
    box: { x: x / width, y: y / height, width: w / width, height: h / height },
    centered,
    sizeOk,
    yaw: eyes.yaw,
    ear: eyes.avgEar,
    leftEar: eyes.leftEar,
    rightEar: eyes.rightEar,
    eyes,
    eyesUsable: eyeVisibility(eyes) === null,
    descriptor: face.descriptor ? Array.from(face.descriptor) : undefined,
  };
}

export function descriptorDistance(a: readonly number[], b: readonly number[]): number {
  let sum = 0;
  for (let i = 0; i < a.length; i++) sum += (a[i] - (b[i] ?? 0)) ** 2;
  return Math.sqrt(sum);
}
