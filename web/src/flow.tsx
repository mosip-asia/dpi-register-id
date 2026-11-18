import { createContext, useContext, useMemo, useState } from "react";

export type FaceScan = {
  descriptors: number[][];
  blinkCount: number;
  sweepYaws: number[];
  challengeId: string;
};

export type FlowState = {
  fullName: string;
  gender: string;
  dateOfBirth: string;
  email: string;
  emailSent: boolean | null;
  consentAccepted: boolean;
  researchOptIn: boolean;
  photoDataUrl: string | null;
  scan: FaceScan | null;
  uin: string | null;
  enrolled: boolean;
  recordStatus: string | null;
  serviceName: string;
  attemptsLeft: number;
  lastMessage: string | null;
  lastDistance: number | null;
  verified: boolean;
  applicationCode: string | null;
  applicationExpiresAt: number | null;
  applicationReason: "no-camera" | "camera-quality" | null;
};

const empty: FlowState = {
  fullName: "",
  gender: "",
  dateOfBirth: "",
  email: "",
  emailSent: null,
  consentAccepted: false,
  researchOptIn: false,
  photoDataUrl: null,
  scan: null,
  uin: null,
  enrolled: false,
  recordStatus: null,
  serviceName: "Sandbox service",
  attemptsLeft: 3,
  lastMessage: null,
  lastDistance: null,
  verified: false,
  applicationCode: null,
  applicationExpiresAt: null,
  applicationReason: null,
};

type FlowApi = FlowState & {
  update: (patch: Partial<FlowState>) => void;
  reset: () => void;
};

const FlowContext = createContext<FlowApi | null>(null);

export function FlowProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<FlowState>(() => {
    const saved = sessionStorage.getItem("register-id-flow");
    if (!saved) return empty;
    try {
      const parsed = JSON.parse(saved) as Partial<FlowState>;
      return { ...empty, ...parsed, verified: false };
    } catch {
      return empty;
    }
  });

  const api = useMemo<FlowApi>(
    () => ({
      ...state,
      update(patch) {
        setState((current) => {
          const next = { ...current, ...patch };
          sessionStorage.setItem("register-id-flow", JSON.stringify({ ...next, verified: false }));
          return next;
        });
      },
      reset() {
        sessionStorage.removeItem("register-id-flow");
        setState(empty);
      },
    }),
    [state],
  );

  return <FlowContext.Provider value={api}>{children}</FlowContext.Provider>;
}

export function useFlow() {
  const value = useContext(FlowContext);
  if (!value) throw new Error("useFlow must be used inside FlowProvider");
  return value;
}
