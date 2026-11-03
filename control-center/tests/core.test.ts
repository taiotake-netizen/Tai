import { describe, expect, it } from "vitest";
import { deriveCore, mergeEvents, newCelebrations } from "@/lib/coreState";
import type { Agent, EventItem, Overview } from "@/lib/types";

const agent = (id: string, state: Agent["state"], kinds: string[] = []): Agent => ({
  id, name: id, role: "", state, connected: true, reason: null, tool: null, queued: 0, last: null,
  running: kinds.map((k, i) => ({ id: i, kind: k, post_id: null, started_at: "" })),
});

function ov(agents: Agent[], extra: Partial<Overview> = {}): Overview {
  return { runtime: { scheduler_alive: true, worker_alive: true, scheduler_last_tick: null, worker_last_seen: null },
    agents, attention: [], ...extra } as unknown as Overview;
}

describe("core visual priority", () => {
  it("disconnected beats everything", () => {
    expect(deriveCore({ reachable: false, overview: ov([agent("a", "error")]), selected: null })).toBe("disconnected");
    const dead = ov([], { runtime: { scheduler_alive: false, worker_alive: true, scheduler_last_tick: null, worker_last_seen: null } });
    expect(deriveCore({ reachable: true, overview: dead, selected: null })).toBe("disconnected");
  });
  it("error > executing > thinking > idle", () => {
    const a = [agent("t", "running", ["publish_post"]), agent("c", "running", ["generate_post"])];
    expect(deriveCore({ reachable: true, overview: ov([...a, agent("x", "error")]), selected: null })).toBe("error");
    expect(deriveCore({ reachable: true, overview: ov(a), selected: null })).toBe("executing");
    expect(deriveCore({ reachable: true, overview: ov(a), selected: "c" })).toBe("thinking");
    expect(deriveCore({ reachable: true, overview: ov([agent("i", "idle")]), selected: null })).toBe("idle");
  });
  it("unknown post outcome shows error overall", () => {
    const o = ov([agent("i", "idle")], { attention: [{ kind: "post", id: 1, status: "unknown", message: null, updated_at: "" }] });
    expect(deriveCore({ reachable: true, overview: o, selected: null })).toBe("error");
  });
});

const ev = (id: string, seq: number, sev: EventItem["severity"] = "success", type = "post.published"): EventItem => ({
  seq, event_id: id, account_id: "a", source_system: "s", event_type: type, severity: sev, occurred_at: "", received_at: "",
  job_id: null, post_id: null, message: "", payload: {},
});

describe("events", () => {
  it("celebrates each success event once", () => {
    const played = new Set<string>(["e1"]);
    expect(newCelebrations([ev("e1", 1), ev("e2", 2), ev("e3", 3, "info")], played).map((e) => e.event_id)).toEqual(["e2"]);
  });
  it("merges with dedupe and ordering (out-of-order delivery)", () => {
    const m = mergeEvents([ev("a", 3), ev("b", 1)], [ev("a", 3), ev("c", 2)]);
    expect(m.map((e) => e.event_id)).toEqual(["b", "c", "a"]);
  });
});
