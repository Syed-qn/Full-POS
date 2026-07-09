import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import App from "./App";
import { syncAuthTokenToDesktopShell } from "./lib/auth";
import { prefersHashRouter } from "./lib/desktopEnv";
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

// Mark body for desktop-specific CSS (window chrome, no browser chrome).
if (prefersHashRouter()) {
  document.body.classList.add("is-desktop");
  document.title = "Full POS";
}

// Packaged .exe / .dmg loads file:// — HashRouter is required.
// Cloud SaaS and vite dev use BrowserRouter (clean URLs).
const Router = prefersHashRouter() ? HashRouter : BrowserRouter;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Router>
        <App />
      </Router>
    </QueryClientProvider>
  </React.StrictMode>,
);
