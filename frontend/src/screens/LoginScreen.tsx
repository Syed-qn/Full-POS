import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, TouchButton } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import { login, setToken, signup } from "../lib/auth";
import {
  clearStaffSession,
  getRoleHomePath,
  setStaffSession,
} from "../lib/navAccess";
import { staffLogin } from "../lib/staffApi";
import { getPairedStore, normalizeStoreCode, setPairedStore } from "../lib/storeIdentity";
import s from "./LoginScreen.module.css";

type Mode = "login" | "signup" | "pin";

export function LoginScreen() {
  // The pairing link — /login?account=<uuid>&location=<uuid> — is the ONLY way
  // a branch reaches this screen; it is never shown or typed. Falls back to
  // whatever this device was last paired with. The link alone opens nothing: a
  // staff number and PIN are still required, checked inside that branch only.
  const [params] = useSearchParams();
  const linkedStore = normalizeStoreCode(
    params.get("location") ?? params.get("store") ?? "",
  );
  // Which business the branch belongs to. Sent alongside the location so a link
  // whose account does not own that branch is refused rather than followed.
  const linkedAccount = (params.get("account") ?? "").trim() || null;
  const [mode, setMode] = useState<Mode>(linkedStore ? "pin" : "login");
  const [name, setName] = useState("");
  // No prefill: the demo account these once held has been deleted, and a
  // prefilled password is a credential shipped in the bundle either way.
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // Staff PIN login routes by role and skips the manager onboarding gate. The
  // staff number is branch-local (every restaurant numbers its own people from
  // 1), so it is only meaningful against the branch the link supplied.
  const [staffId, setStaffId] = useState("");
  const [pin, setPin] = useState("");
  // The link wins over the remembered value, so re-pairing a terminal to
  // another branch is just a new link rather than clearing site data.
  const [storeCode] = useState(linkedStore || getPairedStore());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  const pinDisplay = useMemo(() => "•".repeat(pin.length) || "Enter PIN", [pin]);

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
    setPin("");
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
    const store = normalizeStoreCode(storeCode);
    if (!store) {
      setError("This terminal is not paired with a branch.");
      return;
    }
    const raw = staffId.trim();
    const id = Number(raw);
    // Allow 0 (the owner account) — reject only an empty field, a non-integer,
    // or a negative number. A plain `id <= 0` here locks the owner out.
    if (raw === "" || !Number.isInteger(id) || id < 0) {
      setError("Enter your staff number");
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
      const res = await staffLogin(store, id, pin, linkedAccount);
      // Only remember the code once it has actually opened a session, so a typo
      // never gets pinned to the device.
      setPairedStore(store);
      setToken(res.access_token);
      setStaffSession({
        role: res.role,
        training_mode: Boolean(res.training_mode),
        name: res.name,
        staff_id: res.staff_id,
      });
      nav(getRoleHomePath(res.role), { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : "Invalid staff number or PIN",
      );
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
          {/* Without this tab the signup form below is unreachable — the mode
              exists, the handler exists, but nothing can select it. */}
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

        {mode === "pin" && !storeCode ? (
          // No link opened here and nothing remembered. There is no field to
          // type a branch into any more, so say what to do rather than letting
          // staff punch in a PIN that can never resolve.
          <div className={s.unpaired} role="status">
            <strong>This terminal is not paired with a branch.</strong>
            <span>
              Open the pairing link for this branch — an owner can copy it from
              Settings → General → Terminal pairing link.
            </span>
          </div>
        ) : mode === "pin" ? (
          <form className={s.pinForm} onSubmit={submitPin} noValidate>
            {/* The branch is not shown or typed — it arrives with the pairing
                link and stays on the device. Staff see only their own two
                fields; an unpaired terminal is caught below, before the pad. */}
            <label className={s.field}>
              <span className={s.label}>Staff number</span>
              <input
                aria-label="Staff number"
                inputMode="numeric"
                pattern="[0-9]*"
                value={staffId}
                onChange={(e) => setStaffId(e.target.value.replace(/\D/g, ""))}
                placeholder="Your number at this branch"
                autoComplete="username"
                autoFocus={Boolean(storeCode)}
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
              Staff terminal?{" "}
              <button type="button" className={s.switchLink} onClick={() => switchMode("pin")}>
                Use PIN pad
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
