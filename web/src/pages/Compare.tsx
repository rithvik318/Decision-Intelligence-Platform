import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { WorkspaceNav } from "../components/Layout";
import { Chip, Empty, ErrorBanner, Spinner, formatDate } from "../components/ui";
import { useAsync } from "../hooks";
import type { DecisionComparison } from "../types";

function DiffList({
  title,
  added,
  removed,
}: {
  title: string;
  added: string[];
  removed: string[];
}) {
  if (!added.length && !removed.length) return null;
  return (
    <div className="diff-col">
      <h4>{title}</h4>
      <ul className="list">
        {added.map((item) => (
          <li key={`+${item}`} className="diff-add">
            + {item}
          </li>
        ))}
        {removed.map((item) => (
          <li key={`-${item}`} className="diff-remove">
            − {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Compare() {
  const { workspaceId = "" } = useParams();
  const [params] = useSearchParams();
  const decisions = useAsync(() => api.listDecisions(workspaceId), [workspaceId]);
  const [left, setLeft] = useState(params.get("left") ?? "");
  const [right, setRight] = useState(params.get("right") ?? "");
  const [result, setResult] = useState<DecisionComparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.compare(workspaceId, left, right));
    } catch (err) {
      setError(err);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  const options = decisions.data ?? [];

  return (
    <>
      <div className="page-head">
        <h1>Compare decisions</h1>
        <p>
          A deterministic diff of two decisions in this workspace. No model call is
          made.
        </p>
      </div>
      <WorkspaceNav workspaceId={workspaceId} />

      <ErrorBanner error={decisions.error} />
      {decisions.loading ? (
        <Spinner label="Loading decisions…" />
      ) : options.length < 2 ? (
        <Empty title="Not enough decisions to compare">
          <p>Record at least two decisions — or reassess an existing one.</p>
        </Empty>
      ) : (
        <div className="card">
          <form onSubmit={run}>
            <div className="grid">
              <div className="field">
                <label htmlFor="left">Earlier decision</label>
                <select id="left" value={left} onChange={(e) => setLeft(e.target.value)} required>
                  <option value="">Select…</option>
                  {options.map((d) => (
                    <option key={d.decision_id} value={d.decision_id}>
                      {formatDate(d.created_at)} · {d.recommendation.statement.slice(0, 48)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="right">Later decision</label>
                <select id="right" value={right} onChange={(e) => setRight(e.target.value)} required>
                  <option value="">Select…</option>
                  {options.map((d) => (
                    <option key={d.decision_id} value={d.decision_id}>
                      {formatDate(d.created_at)} · {d.recommendation.statement.slice(0, 48)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <button type="submit" disabled={busy || !left || !right || left === right}>
              {busy ? "Comparing…" : "Compare"}
            </button>
          </form>
        </div>
      )}

      <ErrorBanner error={error} />

      {result ? (
        <>
          <div className="card">
            <h2>Recommendation</h2>
            <dl className="kv">
              <dt>Earlier</dt>
              <dd>{result.left_recommendation}</dd>
              <dt>Later</dt>
              <dd>{result.right_recommendation}</dd>
            </dl>
            <div className="row" style={{ marginTop: 12 }}>
              <Chip tone={result.recommendation_changed ? "warn" : "ok"}>
                {result.recommendation_changed ? "recommendation changed" : "recommendation unchanged"}
              </Chip>
              <Chip tone={result.confidence_changed ? "warn" : "ok"}>
                confidence {result.left_confidence} → {result.right_confidence}
              </Chip>
              <Chip tone={result.status_changed ? "accent" : "neutral"}>
                status {result.left_status} → {result.right_status}
              </Chip>
              {result.right_supersedes_left ? (
                <Chip tone="accent">later supersedes earlier</Chip>
              ) : null}
            </div>
            {result.changed_since_previous.length ? (
              <>
                <h3 style={{ marginTop: 14 }}>Reported as changed</h3>
                <ul>
                  {result.changed_since_previous.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>

          <div className="card">
            <h2>What moved</h2>
            <div className="grid">
              <DiffList title="Evidence" added={result.added_evidence} removed={result.removed_evidence} />
              <DiffList title="Claims" added={result.added_claims} removed={result.removed_claims} />
              <DiffList title="Assumptions" added={result.added_assumptions} removed={result.removed_assumptions} />
              <DiffList title="Risks" added={result.added_risks} removed={result.removed_risks} />
              <DiffList title="Alternatives" added={result.added_alternatives} removed={result.removed_alternatives} />
            </div>
            {!result.added_evidence.length &&
            !result.removed_evidence.length &&
            !result.added_claims.length &&
            !result.removed_claims.length &&
            !result.added_assumptions.length &&
            !result.removed_assumptions.length &&
            !result.added_risks.length &&
            !result.removed_risks.length &&
            !result.added_alternatives.length &&
            !result.removed_alternatives.length ? (
              <p className="muted">
                Nothing was added or removed across evidence, claims, assumptions,
                risks or alternatives.
              </p>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  );
}
