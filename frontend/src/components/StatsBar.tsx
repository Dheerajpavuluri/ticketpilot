import { pct } from "../format";
import type { Stats } from "../types";

export function StatsBar({ stats }: { stats: Stats | null }) {
  const items = [
    { label: "Tickets", value: stats ? String(stats.total_tickets) : "—" },
    { label: "Auto-resolved", value: pct(stats?.auto_resolve_rate) },
    { label: "Avg confidence", value: pct(stats?.avg_confidence) },
    {
      label: "Avg triage",
      value: stats?.avg_latency_ms != null ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s` : "—",
    },
    { label: "Human edits", value: pct(stats?.human_edit_rate) },
    {
      label: "Pending refunds",
      value: stats ? `$${stats.pending_refund_total.toFixed(0)}` : "—",
    },
  ];
  return (
    <dl className="stats">
      {items.map((i) => (
        <div key={i.label} className="stat">
          <dt>{i.label}</dt>
          <dd>{i.value}</dd>
        </div>
      ))}
    </dl>
  );
}
