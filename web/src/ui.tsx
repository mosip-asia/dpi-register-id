import { Link } from "@tanstack/react-router";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

const enrollSteps = [
  { name: "Start", to: "/" },
  { name: "Consent", to: "/enroll/consent" },
  { name: "Details", to: "/enroll/details" },
  { name: "Face check", to: "/enroll/tutorial" },
  { name: "Camera", to: "/enroll/camera" },
  { name: "Photo", to: "/enroll/capture" },
] as const;

const proveSteps = [
  { name: "Service", to: "/prove" },
  { name: "Your ID", to: "/prove/id" },
  { name: "Face check", to: "/prove/check" },
] as const;

export function Frame({
  stepIndex,
  stepCount,
  kicker,
  title,
  lede,
  aside,
  children,
}: {
  stepIndex?: number;
  stepCount?: number;
  kicker?: string;
  title: string;
  lede?: string;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  const reduce = useReducedMotion();
  const steps = stepCount === 3 ? proveSteps : stepCount === 6 ? enrollSteps : [];
  const phoneStep =
    stepIndex && stepCount ? `Step ${stepIndex} of ${stepCount}${kicker ? ` · ${kicker}` : ""}` : kicker;

  return (
    <div className={steps.length === 0 ? "frame is-plain" : "frame"}>
      {steps.length > 0 ? (
        <nav className="rail" aria-label="Progress">
          <ol>
            {steps.map((step, index) => {
              const number = index + 1;
              const done = stepIndex !== undefined && number < stepIndex;
              const current = number === stepIndex;
              const className = current ? "is-current" : done ? "is-done" : undefined;
              return (
                <li key={step.to}>
                  {done ? (
                    <Link to={step.to} className={className}>
                      {step.name}
                    </Link>
                  ) : (
                    <span className={className}>{step.name}</span>
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

export function Shell({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="app-header">
        <div className="lockup">
          <strong className="institute">Asian Institute of Technology</strong>
          <span className="lockup-rule" aria-hidden="true" />
          <div className="brand">
            <strong>register-id</strong>
            <span>Citizen Registration Gateway</span>
          </div>
        </div>
        <span className="lang">EN</span>
      </header>
      {children}
    </>
  );
}
