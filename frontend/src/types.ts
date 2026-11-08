export type Status =
  | "new"
  | "triaging"
  | "needs_review"
  | "auto_resolved"
  | "sent"
  | "rejected"
  | "failed";

export type Priority = "low" | "medium" | "high" | "urgent";

export interface TicketSummary {
  id: string;
  customer_email: string;
  subject: string;
  status: Status;
  created_at: string;
  category: string | null;
  priority: Priority | null;
  sentiment: string | null;
  confidence: number | null;
  needs_human: boolean | null;
}

export interface Triage {
  category: string;
  priority: Priority;
  sentiment: string;
  summary: string;
  order_id: string | null;
  draft_reply: string;
  citations: string[];
  confidence: number;
  needs_human: boolean;
  escalation_reasons: string[];
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
}

export interface TraceStep {
  step: number;
  type: "model" | "tool";
  ms: number;
  // model steps
  text?: string | null;
  tool_calls?: string[];
  input_tokens?: number;
  output_tokens?: number;
  // tool steps
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
}

export interface ReviewEvent {
  action: string;
  actor: string;
  note: string | null;
  final_reply: string | null;
  created_at: string;
}

export interface Refund {
  order_id: string;
  amount: number;
  reason: string;
  status: string;
}

export interface TicketDetail extends TicketSummary {
  body: string;
  error: string | null;
  triage: Triage | null;
  trace: TraceStep[];
  events: ReviewEvent[];
  refunds: Refund[];
}

export interface Stats {
  total_tickets: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  triaged: number;
  auto_resolve_rate: number | null;
  avg_confidence: number | null;
  avg_latency_ms: number | null;
  human_edit_rate: number | null;
  pending_refund_total: number;
  tokens: { input: number; output: number };
  estimated_cost_usd: number | null;
}

export interface Article {
  slug: string;
  title: string;
  category: string;
  body: string;
}
