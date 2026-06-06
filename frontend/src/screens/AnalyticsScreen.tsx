import s from "./AnalyticsScreen.module.css";

export function AnalyticsScreen() {
  return (
    <div className={s.wrap}>
      <span className="label-upper">Analytics</span>
      <p className={s.note}>Analytics dashboard arrives in a later phase (Predictions &amp; reporting).</p>
    </div>
  );
}
