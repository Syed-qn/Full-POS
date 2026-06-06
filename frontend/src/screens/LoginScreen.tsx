import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import { login } from "../lib/auth";
import s from "./LoginScreen.module.css";

export function LoginScreen() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(phone, password);
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.wrap}>
      <form className={s.card} onSubmit={submit}>
        <div className={s.brand}>OPS TERMINAL</div>
        {error && <SectionBanner tone="error">{error}</SectionBanner>}
        <label className={s.field}>
          <span className="label-upper">Phone</span>
          <input
            aria-label="Phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="username"
          />
        </label>
        <label className={s.field}>
          <span className="label-upper">Password</span>
          <input
            aria-label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign In"}
        </Button>
      </form>
    </div>
  );
}
