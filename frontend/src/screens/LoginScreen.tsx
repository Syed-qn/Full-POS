import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, TouchButton } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import { login, setToken, signup } from "../lib/auth";
import { clearStaffSession, setStaffSession } from "../lib/navAccess";
import { staffLogin } from "../lib/staffApi";
import s from "./LoginScreen.module.css";

type Mode = "login" | "signup" | "pin";

const DEVICE_KEY = "pos_device_name";

export function LoginScreen() {
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  // Dev-only convenience prefill — production builds stay empty.
  const [email, setEmail] = useState(import.meta.env.DEV ? "owner@biryani.ae" : "");
  const [password, setPassword] = useState(import.meta.env.DEV ? "password123" : "");
  const [staffId, setStaffId] = useState("");
  const [pin, setPin] = useState("");
  const [deviceName, setDeviceName] = useState(
    () => localStorage.getItem(DEVICE_KEY) ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  const pinDisplay = useMemo(() => "•".repeat(pin.length) || "Enter PIN", [pin]);

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
    setPin("");
  }

  function onDeviceNameChange(value: string) {
    setDeviceName(value);
    if (value.trim()) localStorage.setItem(DEVICE_KEY, value.trim());
    else localStorage.removeItem(DEVICE_KEY);
  }

  function pinPress(key: string) {
    setError(null);
    if (key === "clear") {
      setPin("");
      return;
    }
    if (key === "back") {
      setPin((p) => p.slice(0, -1));
      return;
    }
    setPin((p) => (p.length >= 8 ? p : p + key));
  }

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        if (!name.trim()) {
          setError("Restaurant name is required");
          setBusy(false);
          return;
        }
        await signup(name.trim(), email, password);
      } else {
        await login(email, password);
      }
      // Owner/manager login — no staff role restriction.
      clearStaffSession();
      nav(mode === "signup" ? "/onboarding" : "/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : mode === "signup"
            ? "Signup failed"
            : "Login failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitPin(e?: React.FormEvent) {
    e?.preventDefault();
    const id = Number(staffId.trim());
    if (!Number.isFinite(id) || id <= 0) {
      setError("Enter your staff ID number");
      return;
    }
    if (pin.length < 4) {
      setError("PIN must be at least 4 digits");
      return;
    }
    if (!navigator.onLine) {
      setError(
        "Cloud login is offline. Use a cached staff session on this device when available, or reconnect.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await staffLogin(id, pin);
      setToken(res.access_token);
      setStaffSession({
        role: res.role,
        training_mode: Boolean(res.training_mode),
        name: res.name,
        staff_id: res.staff_id,
      });
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Invalid staff ID or PIN");
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.wrap}>
      <div className={s.bg} />
      <div className={s.card}>
        <div className={s.brand}>
          <span className={s.brandMark}>POS</span>
          <div className={s.brandText}>
            <strong>Full POS</strong>
            <span>Touch terminal · staff sign-in</span>
          </div>
        </div>

        <label className={s.field}>
          <span className={s.label}>This device</span>
          <input
            aria-label="Device name"
            value={deviceName}
            onChange={(e) => onDeviceNameChange(e.target.value)}
            placeholder="e.g. Counter 1 · iPad"
            autoComplete="off"
          />
        </label>

        <div className={s.tabs} role="tablist" aria-label="Sign-in method">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            className={`${s.tab} ${mode === "login" ? s.tabActive : ""}`}
            onClick={() => switchMode("login")}
          >
            SIGN IN
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "pin"}
            className={`${s.tab} ${mode === "pin" ? s.tabActive : ""}`}
            onClick={() => switchMode("pin")}
          >
            STAFF PIN
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signup"}
            className={`${s.tab} ${mode === "signup" ? s.tabActive : ""}`}
            onClick={() => switchMode("signup")}
          >
            SIGN UP
          </button>
        </div>

        {error && (
          <SectionBanner tone="error" onDismiss={() => setError(null)}>
            {error}
          </SectionBanner>
        )}

        {mode === "pin" ? (
          <form className={s.pinForm} onSubmit={submitPin} noValidate>
            <label className={s.field}>
              <span className={s.label}>Staff ID</span>
              <input
                aria-label="Staff ID"
                inputMode="numeric"
                pattern="[0-9]*"
                value={staffId}
                onChange={(e) => setStaffId(e.target.value.replace(/\D/g, ""))}
                placeholder="Your staff number"
                autoComplete="username"
                autoFocus
              />
            </label>

            <div className={s.pinDisplay} aria-live="polite" aria-label="PIN entry">
              {pinDisplay}
            </div>

            <div className={s.pinPad} role="group" aria-label="PIN pad">
              {["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"].map(
                (key) => (
                  <button
                    key={key}
                    type="button"
                    className={`${s.pinKey} ${key === "clear" || key === "back" ? s.pinKeyMuted : ""}`}
                    onClick={() => pinPress(key === "clear" ? "clear" : key === "back" ? "back" : key)}
                    aria-label={
                      key === "clear" ? "Clear PIN" : key === "back" ? "Backspace" : `Digit ${key}`
                    }
                  >
                    {key === "clear" ? "C" : key === "back" ? "⌫" : key}
                  </button>
                ),
              )}
            </div>

            <TouchButton type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign In with PIN"}
            </TouchButton>

            <p className={s.hint}>
              Manager?{" "}
              <button type="button" className={s.switchLink} onClick={() => switchMode("login")}>
                Use email &amp; password
              </button>
            </p>
          </form>
        ) : (
          <form className={s.fields} onSubmit={submitPassword} noValidate>
            {mode === "signup" && (
              <label className={s.field}>
                <span className={s.label}>Restaurant Name</span>
                <input
                  aria-label="Restaurant Name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Biryani House"
                  autoComplete="organization"
                  autoFocus
                />
              </label>
            )}

            <label className={s.field}>
              <span className={s.label}>Email</span>
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
              <span className={s.label}>Password</span>
              <input
                aria-label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
              />
            </label>

            <Button type="submit" size="touch" disabled={busy}>
              {busy
                ? mode === "signup"
                  ? "Creating account…"
                  : "Signing in…"
                : mode === "signup"
                  ? "Create Account"
                  : "Sign In"}
            </Button>

            <p className={s.hint}>
              {mode === "login" ? (
                <>
                  Staff terminal?{" "}
                  <button type="button" className={s.switchLink} onClick={() => switchMode("pin")}>
                    Use PIN pad
                  </button>
                  {" · "}
                  No account?{" "}
                  <button type="button" className={s.switchLink} onClick={() => switchMode("signup")}>
                    Sign up
                  </button>
                </>
              ) : (
                <>
                  Already registered?{" "}
                  <button type="button" className={s.switchLink} onClick={() => switchMode("login")}>
                    Sign in
                  </button>
                </>
              )}
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
