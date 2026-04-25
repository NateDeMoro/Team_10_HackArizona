export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Health = { status: string };

export async function getHealth(): Promise<Health> {
  const res = await fetch(`${API_BASE}/healthz`, { cache: "no-store" });
  if (!res.ok) throw new Error(`healthz ${res.status}`);
  return res.json();
}
