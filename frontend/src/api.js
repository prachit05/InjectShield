// Calls to the InjectShield API. On AWS the page and the API share the CloudFront
// origin, so apiBase is empty; locally it points at the docker compose API.

import { auth } from "./auth.js";

const base = (window.INJECTSHIELD_CONFIG || {}).apiBase || "";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = await auth.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (auth.enabled && !token) throw new ApiError(401, "Your session has ended. Please sign in again.");

  let response;
  try {
    response = await fetch(base + path, { ...options, headers });
  } catch {
    throw new ApiError(0, "Could not reach the InjectShield API.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : null;
    throw new ApiError(response.status, detail || `Request failed (${response.status}).`);
  }
  return data;
}

export const api = {
  scan(prompt, context) {
    const body = { prompt };
    if (context) body.context = context;
    return request("/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  result(jobId) {
    return request(`/result/${encodeURIComponent(jobId)}`);
  },
  jobs(limit = 20) {
    return request(`/jobs?limit=${limit}`);
  },
};
