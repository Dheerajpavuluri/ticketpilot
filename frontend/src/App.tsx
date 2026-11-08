import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Inbox } from "./components/Inbox";
import { NewTicketDialog } from "./components/NewTicketDialog";
import { StatsBar } from "./components/StatsBar";
import { TicketView } from "./components/TicketView";
import type { Stats, TicketSummary } from "./types";

export type Filter = "all" | "needs_review" | "auto_resolved" | "sent" | "failed";

const POLL_MS = 2500;

export default function App() {
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [health, setHealth] = useState<{ provider: string; mode: string } | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const [list, s] = await Promise.all([api.tickets(filter === "all" ? undefined : filter), api.stats()]);
      setTickets(list);
      setStats(s);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [filter]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(() => {
      refresh();
      setTick((n) => n + 1);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!selected && tickets.length) setSelected(tickets[0].id);
  }, [tickets, selected]);

  async function loadDemo() {
    try {
      await api.loadDemo(12);
      setFilter("all");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            TP
          </span>
          <div>
            <h1>TicketPilot</h1>
            <p className="muted small">Brewline support queue</p>
          </div>
        </div>
        <StatsBar stats={stats} />
        <div className="topbar-actions">
          {health && (
            <span className={`mode-pill ${health.provider === "offline" ? "warn" : ""}`}>
              {health.provider === "offline" ? "offline rules" : health.provider} · {health.mode}
            </span>
          )}
          <button className="btn ghost" onClick={loadDemo}>
            Load demo tickets
          </button>
          <button className="btn primary" onClick={() => setShowNew(true)}>
            New ticket
          </button>
        </div>
      </header>

      {error && <div className="banner error">Can't reach the API ({error})</div>}

      <main className="workspace">
        <Inbox
          tickets={tickets}
          filter={filter}
          onFilter={(f) => {
            setFilter(f);
            setSelected(null);
          }}
          selected={selected}
          onSelect={setSelected}
          counts={stats?.by_status ?? {}}
          total={stats?.total_tickets ?? 0}
        />
        {selected ? (
          <TicketView key={selected} id={selected} pollKey={tick} onChanged={refresh} />
        ) : (
          <section className="empty-state">
            <h2>No tickets yet</h2>
            <p className="muted">
              Load the demo set to watch the agent triage 12 real-looking tickets, or write your own.
            </p>
            <div className="row gap">
              <button className="btn primary" onClick={loadDemo}>
                Load demo tickets
              </button>
              <button className="btn ghost" onClick={() => setShowNew(true)}>
                New ticket
              </button>
            </div>
          </section>
        )}
      </main>

      {showNew && (
        <NewTicketDialog
          onClose={() => setShowNew(false)}
          onCreated={(id) => {
            setShowNew(false);
            setFilter("all");
            setSelected(id);
            refresh();
          }}
        />
      )}
    </div>
  );
}
