import type { BacktestRow, ChunkDetail, DebateEvent, DebateSummary, Ipo, Metric } from "./types";

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  ipos: (status?: string) => get<Ipo[]>(`/api/ipos${status ? `?status=${status}` : ""}`),
  ipo: (id: string) => get<Ipo>(`/api/ipos/${id}`),
  metrics: (id: string) => get<Metric[]>(`/api/ipos/${id}/metrics`),
  debates: (id: string) => get<DebateSummary[]>(`/api/ipos/${id}/debates`),
  chunk: (id: string) => get<ChunkDetail>(`/api/chunks/${id}`),
  backtest: () => get<BacktestRow[]>(`/api/backtest`),
};

/** Parse a text/event-stream body and call onEvent for every `data:` payload. */
async function readSse(res: Response, onEvent: (e: DebateEvent) => void): Promise<void> {
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("\n");
      if (data) onEvent(JSON.parse(data) as DebateEvent);
    }
  }
}

export async function streamDebate(ipoId: string, onEvent: (e: DebateEvent) => void, signal?: AbortSignal) {
  const res = await fetch(`/api/ipos/${ipoId}/debate`, { method: "POST", signal });
  await readSse(res, onEvent);
}

export async function streamReplay(debateId: string, onEvent: (e: DebateEvent) => void, signal?: AbortSignal) {
  const res = await fetch(`/api/debates/${debateId}/replay?speed=3`, { signal });
  await readSse(res, onEvent);
}
