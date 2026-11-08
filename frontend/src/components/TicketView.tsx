import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { categoryLabel, confidenceBand, isActive, pct, STATUS_LABEL } from "../format";
import type { Article, TicketDetail } from "../types";
import { TracePanel } from "./TracePanel";

interface Props {
  id: string;
  pollKey: number;
  onChanged: () => void;
}

export function TicketView({ id, pollKey, onChanged }: Props) {
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [reply, setReply] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [article, setArticle] = useState<Article | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const t = await api.ticket(id);
      setTicket(t);
      if (!dirty) setReply(t.triage?.draft_reply ?? "");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id, dirty]);

  useEffect(() => {
    load();
  }, [load, pollKey]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setDirty(false);
      setShowReject(false);
      await load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!ticket) return <section className="ticket-view muted pad">Loading…</section>;

  const tr = ticket.triage;
  const band = confidenceBand(tr?.confidence ?? null);
  const sent = ticket.events.find((e) => e.final_reply);
  const reviewable = ticket.status === "needs_review";

  return (
    <>
      <section className="ticket-view">
        <header className="ticket-head">
          <div>
            <p className="eyebrow">
              #{ticket.id} · {ticket.customer_email}
            </p>
            <h2>{ticket.subject}</h2>
          </div>
          <span className={`status big ${ticket.status}`}>{STATUS_LABEL[ticket.status]}</span>
        </header>

        <article className="message">
          <p>{ticket.body}</p>
        </article>

        {isActive(ticket.status) && (
          <div className="banner info">
            <span className="spinner" aria-hidden /> The agent is working on this ticket…
          </div>
        )}
        {ticket.status === "failed" && <div className="banner error">Triage failed: {ticket.error}</div>}

        {tr && (
          <div className="triage">
            <div className="triage-grid">
              <Field label="Category" value={categoryLabel(tr.category)} />
              <Field label="Priority" value={<span className={`tag prio ${tr.priority}`}>{tr.priority}</span>} />
              <Field label="Sentiment" value={tr.sentiment} />
              <Field label="Order" value={tr.order_id ?? "—"} mono />
              <Field
                label="Confidence"
                value={
                  <span className={`confidence ${band}`}>
                    <span className="meter">
                      <span style={{ width: pct(tr.confidence) }} />
                    </span>
                    {pct(tr.confidence)}
                  </span>
                }
              />
            </div>

            <p className="summary">{tr.summary}</p>

            {tr.escalation_reasons.length > 0 && (
              <div className="reasons">
                <h3>Why a human needs to look</h3>
                <ul>
                  {tr.escalation_reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {ticket.refunds.length > 0 && (
              <div className="refunds">
                {ticket.refunds.map((r, i) => (
                  <div key={i} className="refund">
                    <span>
                      Refund <strong>${r.amount.toFixed(2)}</strong> on <code>{r.order_id}</code>
                    </span>
                    <span className={`tag ${r.status === "approved" ? "ok" : "warn"}`}>{r.status}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="reply">
              <div className="row between">
                <h3>{sent ? "Reply sent" : "Draft reply"}</h3>
                {tr.citations.length > 0 && (
                  <span className="row gap-sm wrap">
                    <span className="muted small">Sources:</span>
                    {tr.citations.map((c) => (
                      <button key={c} className="link small" onClick={() => api.article(c).then(setArticle)}>
                        {c}
                      </button>
                    ))}
                  </span>
                )}
              </div>
              {reviewable ? (
                <textarea
                  id="reply-editor"
                  value={reply}
                  rows={9}
                  onChange={(e) => {
                    setReply(e.target.value);
                    setDirty(true);
                  }}
                />
              ) : (
                <pre className="reply-text">{sent?.final_reply ?? tr.draft_reply}</pre>
              )}
            </div>

            {error && <div className="banner error">{error}</div>}

            <div className="actions">
              {reviewable && (
                <>
                  <button className="btn primary" disabled={busy} onClick={() => act(() => api.approve(id, reply))}>
                    {dirty ? "Send edited reply" : "Approve & send"}
                  </button>
                  <button className="btn ghost" disabled={busy} onClick={() => setShowReject((v) => !v)}>
                    Handle manually
                  </button>
                </>
              )}
              {!["sent", "triaging", "new"].includes(ticket.status) && (
                <button className="btn ghost" disabled={busy} onClick={() => act(() => api.retriage(id))}>
                  Re-run agent
                </button>
              )}
              <span className="muted small push">
                {tr.provider}/{tr.model} · {(tr.latency_ms / 1000).toFixed(2)}s
                {tr.input_tokens + tr.output_tokens > 0 && ` · ${tr.input_tokens + tr.output_tokens} tokens`}
              </span>
            </div>

            {showReject && (
              <form
                className="reject"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (note.trim()) act(() => api.reject(id, note.trim()));
                }}
              >
                <label htmlFor="reject-note">Note for the team</label>
                <input
                  id="reject-note"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. Calling the customer about the sparking unit"
                />
                <button className="btn danger" disabled={busy || !note.trim()}>
                  Take it off the AI queue
                </button>
              </form>
            )}

            {ticket.events.length > 0 && (
              <ol className="timeline">
                {ticket.events.map((e, i) => (
                  <li key={i}>
                    <strong>{e.action.replace("_", " ")}</strong> by {e.actor}
                    {e.note && <> · {e.note}</>}
                    <span className="muted small"> · {new Date(e.created_at).toLocaleString()}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </section>

      <TracePanel trace={ticket.trace} />

      {article && (
        <div className="overlay" role="dialog" aria-modal="true" onClick={() => setArticle(null)}>
          <div className="dialog" onClick={(e) => e.stopPropagation()}>
            <p className="eyebrow">Help center · {article.slug}</p>
            <h2>{article.title}</h2>
            <div className="article-body">{article.body}</div>
            <div className="row end">
              <button className="btn ghost" onClick={() => setArticle(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className={`field-value ${mono ? "mono" : ""}`}>{value}</span>
    </div>
  );
}
