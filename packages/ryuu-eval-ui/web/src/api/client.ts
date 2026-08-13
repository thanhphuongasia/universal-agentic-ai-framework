declare global {
  interface Window {
    RYUU_EVAL_CONFIG?: { apiPrefix?: string };
  }
}

function apiPrefix(): string {
  return window.RYUU_EVAL_CONFIG?.apiPrefix ?? "/api/eval";
}

export function apiUrl(path: string): string {
  return `${apiPrefix()}${path}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}
