import "./app/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { captureToken } from "./app/token";

captureToken(); // must run before the router reads the URL

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
