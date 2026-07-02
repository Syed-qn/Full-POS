import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import { login, signup } from "../lib/auth";
import s from "./LoginScreen.module.css";

type Mode = "login" | "signup";

export function LoginScreen() {
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  // Dev-only convenience prefill — production builds (import.meta.env.DEV === false) stay empty.
  const [email, setEmail] = useState(import.meta.env.DEV ? "owner@biryani.ae" : "");
  const [password, setPassword] = useState(import.meta.env.DEV ? "password123" : "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        if (!name.trim()) { setError("Restaurant name is required"); setBusy(false); return; }
        await signup(name.trim(), email, password);
      } else {
        await login(email, password);
      }
      nav(mode === "signup" ? "/onboarding" : "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : mode === "signup" ? "Signup failed" : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.wrap}>
      <div className={s.bg} />
      <form className={s.card} onSubmit={submit} noValidate>
        <div className={s.brand}>
          <span className={s.brandIcon}>▸</span> OPS TERMINAL
        </div>

        <div className={s.tabs}>
          <button
            type="button"
            className={`${s.tab} ${mode === "login" ? s.tabActive : ""}`}
            onClick={() => switchMode("login")}
          >
            SIGN IN
          </button>
          <button
            type="button"
            className={`${s.tab} ${mode === "signup" ? s.tabActive : ""}`}
            onClick={() => switchMode("signup")}
          >
            SIGN UP
          </button>
          <div className={s.tabSlider} style={{ left: mode === "login" ? 0 : "50%" }} />
        </div>

        {error && <SectionBanner tone="error">{error}</SectionBanner>}

        <div className={`${s.fields} ${mode === "signup" ? s.fieldsExpanded : ""}`}>
          {mode === "signup" && (
            <label className={s.field}>
              <span className="label-upper">Restaurant Name</span>
              <input
                aria-label="Restaurant Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Biryani House"
                autoComplete="organization"
                autoFocus={mode === "signup"}
              />
            </label>
          )}

          <label className={s.field}>
            <span className="label-upper">Email</span>
            <input
              aria-label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@restaurant.com"
              autoComplete="username"
              autoFocus={mode === "login"}
            />
          </label>

          <label className={s.field}>
            <span className="label-upper">Password</span>
            <input
              aria-label="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
            />
          </label>
        </div>

        <Button type="submit" disabled={busy}>
          {busy
            ? mode === "signup" ? "Creating account…" : "Signing in…"
            : mode === "signup" ? "Create Account" : "Sign In"}
        </Button>

        <p className={s.hint}>
          {mode === "login"
            ? <>No account? <button type="button" className={s.switchLink} onClick={() => switchMode("signup")}>Sign up</button></>
            : <>Already registered? <button type="button" className={s.switchLink} onClick={() => switchMode("login")}>Sign in</button></>
          }
        </p>
      </form>
    </div>
  );
}
