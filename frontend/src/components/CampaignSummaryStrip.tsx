import type { CampaignSummary } from "../lib/campaignSummary";
import s from "./CampaignSummaryStrip.module.css";

export function CampaignSummarySkeleton() {
  return (
    <div className={s.row} aria-busy="true" aria-label="Loading campaign summary">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={s.box}>
          <span className={`${s.sk} ${s.skNum}`} />
          <span className={`${s.sk} ${s.skLabel}`} />
        </div>
      ))}
    </div>
  );
}

export function CampaignSummaryStrip({ summary }: { summary: CampaignSummary }) {
  return (
    <div className={s.row}>
      <div className={s.box}>
        <div className={s.num}>{summary.campaignsSent}</div>
        <div className={s.label}>Campaigns sent</div>
      </div>
      <div className={s.box}>
        <div className={s.num}>{summary.messagesDelivered}</div>
        <div className={s.label}>Messages delivered</div>
      </div>
      <div className={s.box}>
        <div className={s.num}>{summary.ordersFromCampaigns}</div>
        <div className={s.label}>Orders from campaigns</div>
      </div>
      <div className={s.box}>
        <div className={s.num}>{summary.successRate}%</div>
        <div className={s.label}>Success rate</div>
      </div>
    </div>
  );
}