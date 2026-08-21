import type { ReactNode } from "react";
import { ApiError } from "../api";
import type { Level } from "../types";

export function Spinner({ label }: { label: string }) {
  return (
    <div className="progress" role="status" aria-live="polite">
      <span className="dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  const message = error instanceof Error ? error.message : String(error);
  const rateLimited = api?.status === 429;
  return (
    <div className={`banner ${rateLimited ? "warn" : ""}`} role="alert">
      <strong>{rateLimited ? "Rate limited. " : "Something went wrong. "}</strong>
      {message}
      {rateLimited && api?.retryAfterSeconds ? (
        <> Try again in about {api.retryAfterSeconds} seconds.</>
      ) : null}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "ok" | "warn" | "danger";
}) {
  return <span className={`chip ${tone === "neutral" ? "" : tone}`}>{children}</span>;
}

/** Confidence and severity are three-level model judgements, not measurements. */
export function LevelChip({ level, kind }: { level: Level; kind: "confidence" | "severity" }) {
  const tone =
    kind === "confidence"
      ? level === "high"
        ? "ok"
        : level === "medium"
          ? "accent"
          : "warn"
      : level === "high"
        ? "danger"
        : level === "medium"
          ? "warn"
          : "neutral";
  return <Chip tone={tone as never}>{`${kind} · ${level}`}</Chip>;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
