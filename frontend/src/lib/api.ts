export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    if (res.status === 401) throw new ApiError(401, "Not authenticated");
    let detail = res.statusText.trim() || `Request failed with HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      const responseDetail = body.detail === undefined ? "" : String(body.detail).trim();
      if (responseDetail) detail = responseDetail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
