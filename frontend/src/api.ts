import type { Article, Stats, TicketDetail, TicketSummary } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ provider: string; mode: string }>("/health"),
  tickets: (status?: string) =>
    request<TicketSummary[]>(`/tickets${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  ticket: (id: string) => request<TicketDetail>(`/tickets/${id}`),
  create: (body: { customer_email: string; subject: string; body: string }) =>
    request<TicketSummary>("/tickets", { method: "POST", body: JSON.stringify(body) }),
  approve: (id: string, reply: string) =>
    request<TicketDetail>(`/tickets/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ reply, actor: "you" }),
    }),
  reject: (id: string, note: string) =>
    request<TicketDetail>(`/tickets/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ note, actor: "you" }),
    }),
  retriage: (id: string) => request<{ status: string }>(`/tickets/${id}/retriage`, { method: "POST" }),
  stats: () => request<Stats>("/stats"),
  article: (slug: string) => request<Article>(`/articles/${slug}`),
  loadDemo: (limit = 12) => request<{ loaded: number }>(`/demo/load?limit=${limit}`, { method: "POST" }),
};
