import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FlowProvider } from "./flow";
import { AppRouter } from "./router";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("root element is missing");

createRoot(root).render(
  <StrictMode>
    <FlowProvider>
      <AppRouter />
    </FlowProvider>
  </StrictMode>,
);
