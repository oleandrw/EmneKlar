import "./design-system/styles/tokens.css";
import "./design-system/styles/base.css";
import "./design-system/styles/components.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
