import { Link } from "@tanstack/react-router";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { useFlow } from "./flow";

const enrollSteps = [
  { name: "Start", to: "/" },
  { name: "Consent", to: "/enroll/consent" },
  { name: "Details", to: "/enroll/details" },
  { name: "Face check", to: "/enroll/tutorial" },
  { name: "Camera", to: "/enroll/camera" },
  { name: "Photo", to: "/enroll/capture" },
  { name: "Review", to: "/enroll/review" },
  { name: "ID", to: "/enroll/ready" },
] as const;

const proveSteps = [
  { name: "Service", to: "/prove" },
  { name: "Your ID", to: "/prove/id" },
  { name: "Face check", to: "/prove/check" },
  { name: "Result", to: "/prove/verified" },
] as const;

export function Frame({
  stepIndex,
  stepCount,
  kicker,
  title,
  lede,
  aside,
  wide = false,
  children,
}: {
  stepIndex?: number;
  stepCount?: number;
  kicker?: string;
  title: string;
  lede?: string;
  aside?: ReactNode;
  wide?: boolean;
  children?: ReactNode;
}) {
  const reduce = useReducedMotion();
  const flow = useFlow();
  const steps = stepCount === 4 ? proveSteps : stepCount === 8 ? enrollSteps : [];
  const pastEnd = Boolean(stepIndex && steps.length > 0 && stepIndex > steps.length);
  const phoneStep =
    stepIndex && stepCount && stepIndex <= stepCount
      ? `Step ${stepIndex} of ${stepCount}${kicker ? `, ${kicker}` : ""}`
      : kicker;

  const frameClass = ["frame", steps.length === 0 ? "is-plain" : "", wide ? "is-wide" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={frameClass}>
      {steps.length > 0 ? (
        <nav className="rail" aria-label="Progress">
          <ol>
            {steps.map((step, index) => {
              const number = index + 1;
              const done = pastEnd || (stepIndex !== undefined && number < stepIndex);
              const current = !pastEnd && number === stepIndex;
              const className = current ? "is-current" : done ? "is-done" : undefined;
              const reviewStillOpen = Boolean(flow.photoDataUrl && flow.scan);
              const canOpen = step.to !== "/enroll/review" || reviewStillOpen;
              return (
                <li key={step.to}>
                  {done && canOpen ? (
                    <Link to={step.to} className={className}>
                      {step.name}
                    </Link>
                  ) : (
                    <span className={className} aria-current={current ? "step" : undefined}>
                      {step.name}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      ) : null}
      <motion.div
        className="frame-body"
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.16, ease: [0.2, 0, 0, 1] }}
      >
        {phoneStep ? <p className="kicker">{phoneStep}</p> : null}
        <h1>{title}</h1>
        {lede ? <p className="lede">{lede}</p> : null}
        {children}
      </motion.div>
      {aside ? <aside className="aside">{aside}</aside> : null}
    </div>
  );
}

export function CopyValue({ value }: { value: string }) {
  const [state, setState] = useState<"idle" | "loading" | "success" | "error">("idle");

  useEffect(() => {
    if (state !== "success" && state !== "error") return;
    const timer = window.setTimeout(() => setState("idle"), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);

  async function onCopy() {
    setState("loading");
    try {
      await navigator.clipboard.writeText(value);
      setState("success");
    } catch {
      setState("error");
    }
  }

  const label =
    state === "loading" ? "Copying" : state === "success" ? "Copied" : state === "error" ? "Copy failed" : "Copy";

  return (
    <button
      type="button"
      className="quiet"
      data-state={state === "idle" ? undefined : state}
      disabled={state === "loading"}
      onClick={() => void onCopy()}
    >
      {label}
    </button>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="app-header">
        <div className="lockup">
          <strong className="institute">Asian Institute of Technology</strong>
          <span className="lockup-rule" aria-hidden="true" />
          <div className="brand-block">
            <Link to="/" className="brand">
              register-id
            </Link>
            <span className="brand-note">Citizen Registration Gateway</span>
          </div>
        </div>
        <nav className="app-nav" aria-label="Portal">
          <Link to="/enroll/consent">Enroll</Link>
          <Link to="/prove">Prove</Link>
          <Link to="/id">My ID</Link>
          <Link to="/desk">Desk</Link>
        </nav>
      </header>
      {children}
    </>
  );
}
