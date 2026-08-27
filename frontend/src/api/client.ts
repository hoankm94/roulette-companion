import type { ApiError } from "./types";

export class ApiClientError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  init?: { signal?: AbortSignal },
): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: init?.signal,
  });
  return parseResponse<T>(res);
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path);
  return parseResponse<T>(res);
}

async function parseResponse<T>(res: Response): Promise<T> {
  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiClientError(res.status, "parse", "Invalid response from server.");
    }
  }
  if (!res.ok) {
    const err = data as ApiError | null;
    const detail =
      (typeof err?.detail === "string" && err.detail) ||
      (typeof err?.error === "string" && err.error) ||
      `Request failed (${res.status})`;
    throw new ApiClientError(res.status, err?.error || "http", detail);
  }
  return data as T;
}
