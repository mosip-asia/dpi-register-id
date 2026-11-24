import {
  createRootRoute,
  createRoute,
  createRouter,
  Navigate,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useFlow } from "./flow";
import { Activity } from "./screens/Activity";
import { CameraAccess } from "./screens/CameraAccess";
import { Capture } from "./screens/Capture";
import { Consent } from "./screens/Consent";
import { Desk } from "./screens/Desk";
import { Details } from "./screens/Details";
import { FaceCheck } from "./screens/FaceCheck";
import { FixDetail } from "./screens/FixDetail";
import { Help } from "./screens/Help";
import { Landing } from "./screens/Landing";
import { MyId } from "./screens/MyId";
import { Paused } from "./screens/Paused";
import { Ready } from "./screens/Ready";
import { Review } from "./screens/Review";
import { ServiceAsks } from "./screens/ServiceAsks";
import { Tutorial } from "./screens/Tutorial";
import { Unmatched } from "./screens/Unmatched";
import { Verified } from "./screens/Verified";
import { YourId } from "./screens/YourId";
import { Shell } from "./ui";

const rootRoute = createRootRoute({
  component: () => (
    <Shell>
      <Outlet />
    </Shell>
  ),
});

function route<const T extends string>(path: T, component: () => ReactNode) {
  return createRoute({ getParentRoute: () => rootRoute, path, component });
}

function EnrollDetails() {
  const { consentAccepted } = useFlow();
  if (!consentAccepted) return <Navigate to="/enroll/consent" />;
  return <Details />;
}

function afterDetails(Screen: () => ReactNode) {
  return function GatedStep() {
    const flow = useFlow();
    if (!flow.consentAccepted) return <Navigate to="/enroll/consent" />;
    const ready =
      flow.fullName.trim() !== "" &&
      flow.dateOfBirth.trim() !== "" &&
      flow.gender.trim() !== "" &&
      flow.email.trim() !== "";
    if (!ready) return <Navigate to="/enroll/details" />;
    return <Screen />;
  };
}

function afterScan(Screen: () => ReactNode, { allowEnrolled = false } = {}) {
  return afterDetails(function ScannedStep() {
    const flow = useFlow();
    const scanned = Boolean(flow.photoDataUrl && flow.scan);
    // Ready keeps showing the new ID after enrollment clears the face data.
    const issued = allowEnrolled && flow.enrolled && Boolean(flow.uin);
    if (!scanned && !issued) return <Navigate to="/enroll/capture" />;
    return <Screen />;
  });
}

function ProveCheck() {
  const { uin } = useFlow();
  if (!(uin ?? "").trim()) return <Navigate to="/prove/id" />;
  return <FaceCheck />;
}

const routeTree = rootRoute.addChildren([
  route("/", Landing),
  route("/enroll/details", EnrollDetails),
  route("/enroll/consent", Consent),
  route("/enroll/tutorial", afterDetails(Tutorial)),
  route("/enroll/camera", afterDetails(CameraAccess)),
  route("/enroll/capture", afterDetails(Capture)),
  route("/enroll/help", Help),
  route("/enroll/paused", Paused),
  route("/enroll/review", afterScan(Review)),
  route("/enroll/fix", afterDetails(FixDetail)),
  route("/enroll/ready", afterScan(Ready, { allowEnrolled: true })),
  route("/prove", ServiceAsks),
  route("/prove/id", YourId),
  route("/prove/check", ProveCheck),
  route("/prove/verified", Verified),
  route("/prove/unmatched", Unmatched),
  route("/id", MyId),
  route("/id/activity", Activity),
  route("/desk", Desk),
]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function AppRouter() {
  return <RouterProvider router={router} />;
}
