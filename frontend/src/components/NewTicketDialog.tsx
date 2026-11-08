import { useState } from "react";
import { api } from "../api";

const EXAMPLES = [
  {
    customer_email: "daniel.kim@example.com",
    subject: "Kettle stopped heating",
    body: "My pour-over kettle from order BL-48177 stopped heating after a week. The light turns on but the water stays cold.",
  },
  {
    customer_email: "grace.liu@example.com",
    subject: "Charged twice",
    body: "My card shows two charges of $878 for order BL-48444. Please fix this.",
  },
  {
    customer_email: "tom.fischer@example.com",
    subject: "Skip December box",
    body: "I'm traveling in December, can I skip my next subscription box?",
  },
];

interface Props {
  onClose: () => void;
  onCreated: (id: string) => void;
}

export function NewTicketDialog({ onClose, onCreated }: Props) {
  const [form, setForm] = useState({ customer_email: "", subject: "", body: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const t = await api.create(form);
      onCreated(t.id);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="new-ticket-title" onClick={onClose}>
      <form className="dialog" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2 id="new-ticket-title">New ticket</h2>
        <p className="muted small">
          Write as a customer. Try an email from the sample store, e.g. <code>maya.chen@example.com</code>.
        </p>
        <div className="row gap-sm wrap">
          {EXAMPLES.map((ex) => (
            <button type="button" key={ex.subject} className="chip" onClick={() => setForm(ex)}>
              {ex.subject}
            </button>
          ))}
        </div>
        <label htmlFor="nt-email">Customer email</label>
        <input
          id="nt-email"
          type="email"
          required
          value={form.customer_email}
          onChange={(e) => setForm({ ...form, customer_email: e.target.value })}
        />
        <label htmlFor="nt-subject">Subject</label>
        <input
          id="nt-subject"
          required
          value={form.subject}
          onChange={(e) => setForm({ ...form, subject: e.target.value })}
        />
        <label htmlFor="nt-body">Message</label>
        <textarea
          id="nt-body"
          required
          rows={6}
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
        />
        {error && <div className="banner error">{error}</div>}
        <div className="row end gap">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? "Submitting…" : "Submit ticket"}
          </button>
        </div>
      </form>
    </div>
  );
}
