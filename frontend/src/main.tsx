import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { syncAuthTokenToDesktopShell } from "./lib/auth";
import { capturePartnerFromUrl } from "./lib/partner";
import { queryClient } from "./lib/queryClient";
import "leaflet/dist/leaflet.css";
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";

// Capture ?partner=<slug> before any routing so it survives signup -> onboarding.
capturePartnerFromUrl();

// Inside the Electron shell, the main process starts with no auth token every
// launch — push whatever's already in localStorage (a prior login) to it now.
// No-op on the plain web app (no window.posBridge there).
syncAuthTokenToDesktopShell();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
