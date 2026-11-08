import { describe, expect, it } from "vitest";
import { categoryLabel, confidenceBand, pct, relativeTime } from "./format";

describe("format helpers", () => {
  it("labels categories", () => {
    expect(categoryLabel("returns_refunds")).toBe("Returns / refunds");
    expect(categoryLabel(null)).toBe("—");
  });

  it("formats percentages", () => {
    expect(pct(0.556)).toBe("56%");
    expect(pct(null)).toBe("—");
  });

  it("bands confidence the same way the backend policy does", () => {
    expect(confidenceBand(0.85)).toBe("high");
    expect(confidenceBand(0.7)).toBe("mid");
    expect(confidenceBand(0.2)).toBe("low");
  });

  it("formats relative time", () => {
    const now = new Date("2026-11-08T12:00:00Z");
    expect(relativeTime("2026-11-08T11:59:30Z", now)).toBe("just now");
    expect(relativeTime("2026-11-08T11:15:00Z", now)).toBe("45m ago");
    expect(relativeTime("2026-11-06T12:00:00Z", now)).toBe("2d ago");
  });
});
