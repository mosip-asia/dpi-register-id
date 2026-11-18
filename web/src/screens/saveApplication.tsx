import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ApiError, createApplication, type ApplicationReason } from "../api";
import { useFlow } from "../flow";

const consentPurpose = "Create a citizen ID and store the face image for this registration";

export function useSaveApplication() {
  const flow = useFlow();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function saveApplication(reason: ApplicationReason) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError(null);
    try {
      const result = await createApplication({
        fullName: flow.fullName,
        gender: flow.gender,
        dateOfBirth: flow.dateOfBirth,
        email: flow.email,
        researchOptIn: flow.researchOptIn,
        reason,
        consent: {
          accepted: true,
          purpose: consentPurpose,
          acceptedAt: Date.now() / 1000,
          language: "eng",
        },
      });
      if (!alive.current) return;
      flushSync(() => {
        flow.update({
          applicationCode: result.code,
          applicationExpiresAt: result.expiresAt,
          applicationReason: reason,
        });
      });
      await navigate({ to: "/enroll/paused" });
    } catch (caught) {
      if (!alive.current) return;
      setError(
        caught instanceof ApiError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : "The application was not saved.",
      );
    } finally {
      busy.current = false;
      if (alive.current) setPending(false);
    }
  }

  return { pending, error, saveApplication };
}

export function ApplicationSaveNotice({ pending, error }: { pending: boolean; error: string | null }) {
  if (pending) {
    return (
      <p className="status" role="status">
        Saving the application…
      </p>
    );
  }
  if (error) {
    return (
      <p className="note" role="alert">
        {error}
      </p>
    );
  }
  return null;
}
