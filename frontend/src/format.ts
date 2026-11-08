import type { Status } from "./types";

export const STATUS_LABEL: Record<Status, string> = {
  new: "New",
  triaging: "Triaging",
  needs_review: "Needs review",
  auto_resolved: "Auto-resolved",
  sent: "Sent",
  rejected: "Rejected",
  failed: "Failed",
};

export function categoryLabel(c: string | null): string {
  if (!c) return "—";
  return c.replace(/_/g, " / ").replace(/^\w/, (m) => m.toUpperCase());
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const diff = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function confidenceBand(c: number | null): "high" | "mid" | "low" | "none" {
  if (c === null) return "none";
  if (c >= 0.8) return "high";
  if (c >= 0.6) return "mid";
  return "low";
}

export function isActive(status: Status): boolean {
  return status === "new" || status === "triaging";
}
