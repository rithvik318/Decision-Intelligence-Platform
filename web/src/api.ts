import type {
  ChatAnswer,
  Decision,
  DecisionComparison,
  DecisionFreshness,
  DecisionProvenance,
  IngestResult,
  IngestedDocument,
  ValidationResult,
  Workspace,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** An API failure with a message worth showing the user. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function messageFor(status: number, detail: string | undefined): string {
  if (detail) return detail;
  switch (status) {
    case 400:
      return "That request was rejected. Check the values and try again.";
    case 404:
      return "Not found.";
    case 422:
      return "Some of the values sent were not valid.";
    case 429:
      return "The model provider is rate-limiting requests.";
    case 502:
      return "The model did not return a usable answer.";
    case 504:
      return "The request took too long and timed out.";
    default:
      return `The server returned an unexpected error (${status}).`;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : undefined;
    } catch {
      /* a non-JSON error body is fine; fall back to the status message */
    }
    const retryAfter = response.headers.get("retry-after");
    throw new ApiError(
      response.status,
      messageFor(response.status, detail),
      retryAfter ? Number(retryAfter) : undefined,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<{ status: string }>("/health"),

  listWorkspaces: () => request<Workspace[]>("/workspaces"),
  getWorkspace: (id: string) => request<Workspace>(`/workspaces/${id}`),
  createWorkspace: (name: string, description: string) =>
    post<Workspace>("/workspaces", { name, description }),

  listDocuments: (id: string) =>
    request<IngestedDocument[]>(`/workspaces/${id}/documents`),
  ingestText: (
    id: string,
    documents: { content: string; file_name: string }[],
    buildGraph: boolean,
  ) =>
    post<IngestResult>(`/workspaces/${id}/ingest`, {
      documents,
      build_graph: buildGraph,
    }),
  ingestPaths: (id: string, paths: string[], buildGraph: boolean) =>
    post<IngestResult>(`/workspaces/${id}/ingest`, {
      paths,
      build_graph: buildGraph,
    }),
  buildGraph: (id: string) =>
    post<{ workspace_id: string; status: string }>(`/workspaces/${id}/graph`, {}),

  chat: (id: string, message: string, sessionId: string) =>
    post<ChatAnswer>(`/workspaces/${id}/chat`, {
      message,
      session_id: sessionId,
    }),

  listDecisions: (id: string) =>
    request<Decision[]>(`/workspaces/${id}/decisions?limit=50`),
  getDecision: (id: string, decisionId: string) =>
    request<Decision>(`/workspaces/${id}/decisions/${decisionId}`),
  createDecision: (id: string, question: string, sessionId: string) =>
    post<Decision>(`/workspaces/${id}/decisions`, {
      question,
      session_id: sessionId,
    }),
  reassess: (id: string, decisionId: string, sessionId: string) =>
    post<Decision>(`/workspaces/${id}/decisions/${decisionId}/reassess`, {
      session_id: sessionId,
    }),
  provenance: (id: string, decisionId: string) =>
    request<DecisionProvenance>(
      `/workspaces/${id}/decisions/${decisionId}/provenance`,
    ),
  validation: (id: string, decisionId: string) =>
    request<ValidationResult>(
      `/workspaces/${id}/decisions/${decisionId}/validation`,
    ),
  freshness: (id: string, decisionId: string) =>
    request<DecisionFreshness>(
      `/workspaces/${id}/decisions/${decisionId}/freshness`,
    ),
  compare: (id: string, leftId: string, rightId: string) =>
    request<DecisionComparison>(
      `/workspaces/${id}/decisions/${leftId}/compare/${rightId}`,
    ),
};
