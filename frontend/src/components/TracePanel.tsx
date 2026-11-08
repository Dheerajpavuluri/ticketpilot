import { useState } from "react";
import type { TraceStep } from "../types";

const TOOL_LABEL: Record<string, string> = {
  lookup_customer: "Looked up customer",
  get_order: "Fetched order",
  search_help_center: "Searched help center",
  create_refund_request: "Opened refund request",
  submit_triage: "Submitted triage",
};

function summarize(step: TraceStep): string {
  const r = step.result as Record<string, unknown> | undefined;
  if (r && typeof r === "object" && "error" in r) return `error: ${String(r.error)}`;
  switch (step.tool) {
    case "lookup_customer":
      return r?.found ? `${r.name}${r.vip ? " · VIP" : ""}` : "not found";
    case "get_order":
      return `${r?.order_id} · ${r?.status} · $${r?.total}`;
    case "search_help_center": {
      const hits = (r?.results as { slug: string }[] | undefined) ?? [];
      return hits.length ? hits.map((h) => h.slug).join(", ") : "no matches";
    }
    case "create_refund_request":
      return `$${r?.amount} · ${r?.status}`;
    case "submit_triage":
      return "done";
    default:
      return "";
  }
}

export function TracePanel({ trace }: { trace: TraceStep[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const tools = trace.filter((s) => s.type === "tool");
  const modelCalls = trace.filter((s) => s.type === "model").length;

  return (
    <aside className="trace">
      <h3>Agent trace</h3>
      <p className="muted small">
        {modelCalls} model {modelCalls === 1 ? "call" : "calls"} · {tools.length} tool{" "}
        {tools.length === 1 ? "call" : "calls"}
      </p>
      {trace.length === 0 && <p className="muted small">No trace yet.</p>}
      <ol className="trace-steps">
        {tools.map((s, i) => (
          <li key={i} className={`trace-step ${s.tool}`}>
            <button className="trace-head" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
              <span className="trace-dot" aria-hidden />
              <span className="trace-title">
                {TOOL_LABEL[s.tool ?? ""] ?? s.tool}
                <span className="muted small block">{summarize(s)}</span>
              </span>
              <span className="muted small mono">{s.ms}ms</span>
            </button>
            {open === i && (
              <div className="trace-body">
                <p className="field-label">Arguments</p>
                <pre>{JSON.stringify(s.args, null, 2)}</pre>
                <p className="field-label">Result</p>
                <pre>{JSON.stringify(s.result, null, 2)}</pre>
              </div>
            )}
          </li>
        ))}
      </ol>
    </aside>
  );
}
