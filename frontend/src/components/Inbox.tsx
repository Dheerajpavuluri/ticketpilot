import type { Filter } from "../App";
import { categoryLabel, relativeTime, STATUS_LABEL } from "../format";
import type { TicketSummary } from "../types";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "needs_review", label: "Needs review" },
  { key: "auto_resolved", label: "Auto-resolved" },
  { key: "sent", label: "Sent" },
  { key: "failed", label: "Failed" },
];

interface Props {
  tickets: TicketSummary[];
  filter: Filter;
  onFilter: (f: Filter) => void;
  selected: string | null;
  onSelect: (id: string) => void;
  counts: Record<string, number>;
  total: number;
}

export function Inbox({ tickets, filter, onFilter, selected, onSelect, counts, total }: Props) {
  return (
    <aside className="inbox">
      <nav className="filters" aria-label="Filter tickets">
        {FILTERS.map((f) => {
          const n = f.key === "all" ? total : counts[f.key] ?? 0;
          return (
            <button
              key={f.key}
              className={`filter ${filter === f.key ? "active" : ""}`}
              onClick={() => onFilter(f.key)}
            >
              {f.label}
              <span className="count">{n}</span>
            </button>
          );
        })}
      </nav>
      <ul className="ticket-list">
        {tickets.length === 0 && <li className="muted small pad">Nothing here.</li>}
        {tickets.map((t) => (
          <li key={t.id}>
            <button
              className={`ticket-row ${selected === t.id ? "selected" : ""}`}
              onClick={() => onSelect(t.id)}
            >
              <span className={`prio-stripe ${t.priority ?? "none"}`} aria-hidden />
              <span className="ticket-row-main">
                <span className="row between">
                  <span className="subject">{t.subject}</span>
                  <span className="muted small nowrap">{relativeTime(t.created_at)}</span>
                </span>
                <span className="muted small ellipsis">{t.customer_email}</span>
                <span className="row gap-sm wrap">
                  <span className={`status ${t.status}`}>{STATUS_LABEL[t.status]}</span>
                  {t.category && <span className="tag">{categoryLabel(t.category)}</span>}
                  {t.priority && <span className={`tag prio ${t.priority}`}>{t.priority}</span>}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
