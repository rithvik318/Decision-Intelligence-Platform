import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { WorkspaceNav } from "../components/Layout";
import {
  Chip,
  Empty,
  ErrorBanner,
  LevelChip,
  Spinner,
  formatDate,
} from "../components/ui";
import { useAsync } from "../hooks";

type Tab = "analysis" | "provenance" | "validation";

export function DecisionDetail() {
  const { workspaceId = "", decisionId = "" } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("analysis");
  const [reassessing, setReassessing] = useState(false);
  const [reassessError, setReassessError] = useState<unknown>(null);

  const bundle = useAsync(
    async () => {
      const [decision, provenance, validation, freshness] = await Promise.all([
        api.getDecision(workspaceId, decisionId),
        api.provenance(workspaceId, decisionId),
        api.validation(workspaceId, decisionId),
        api.freshness(workspaceId, decisionId),
      ]);
      return { decision, provenance, validation, freshness };
    },
    [workspaceId, decisionId],
  );

  async function reassess() {
    setReassessing(true);
    setReassessError(null);
    try {
      const next = await api.reassess(workspaceId, decisionId, "web");
      navigate(`/w/${workspaceId}/decisions/${next.decision_id}`);
    } catch (err) {
      setReassessError(err);
    } finally {
      setReassessing(false);
    }
  }

  if (bundle.loading) return <Spinner label="Loading decision…" />;
  if (bundle.error) return <ErrorBanner error={bundle.error} />;
  if (!bundle.data) return null;

  const { decision, provenance, validation, freshness } = bundle.data;
  const evidenceById = new Map(decision.evidence.map((e) => [e.evidence_id, e]));

  return (
    <>
      <div className="page-head">
        <h1>{decision.question}</h1>
        <p>
          Decided {formatDate(decision.created_at)} · <code>{decision.decision_id}</code>
        </p>
      </div>
      <WorkspaceNav workspaceId={workspaceId} />

      {freshness.stale ? (
        <div className="banner warn">
          <strong>This decision may be out of date. </strong>
          {freshness.summary}
          {freshness.documents_added_since.length ? (
            <> Added since: {freshness.documents_added_since.join(", ")}.</>
          ) : null}
        </div>
      ) : (
        <div className="banner ok">{freshness.summary}</div>
      )}
      <ErrorBanner error={reassessError} />
      {reassessing ? (
        <Spinner label="Reassessing against current workspace knowledge…" />
      ) : null}

      <div className="card">
        <div className="spread">
          <div>
            <h2 style={{ fontSize: 18 }}>{decision.recommendation.statement}</h2>
            <p style={{ marginTop: 8 }}>{decision.recommendation.rationale}</p>
          </div>
          <div className="stack" style={{ alignItems: "flex-end" }}>
            <LevelChip level={decision.recommendation.confidence} kind="confidence" />
            <Chip tone={decision.status === "reassessed" ? "accent" : "neutral"}>
              {decision.status}
            </Chip>
            <button onClick={reassess} disabled={reassessing}>
              {reassessing ? "Reassessing…" : "Reassess"}
            </button>
          </div>
        </div>
        <p className="muted" style={{ marginTop: 12, marginBottom: 0 }}>
          Confidence is the model's own three-level judgement, not a measured score.
        </p>
      </div>

      {decision.supersedes ? (
        <div className="card">
          <h2>Reassessment</h2>
          <p>
            This decision supersedes{" "}
            <Link to={`/w/${workspaceId}/decisions/${decision.supersedes}`}>
              an earlier decision
            </Link>{" "}
            ·{" "}
            <Link
              to={`/w/${workspaceId}/compare?left=${decision.supersedes}&right=${decision.decision_id}`}
            >
              compare them
            </Link>
          </p>
          {decision.changed_since_previous.length ? (
            <>
              <h3>What changed</h3>
              <ul>
                {decision.changed_since_previous.map((change) => (
                  <li key={change}>{change}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted">
              The reassessment reported no material change from the previous decision.
            </p>
          )}
        </div>
      ) : null}

      <div className="tabs" role="tablist">
        {(["analysis", "provenance", "validation"] as Tab[]).map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? "active" : ""}
            onClick={() => setTab(name)}
          >
            {name === "analysis"
              ? "Analysis"
              : name === "provenance"
                ? "Provenance"
                : `Validation${validation.valid ? "" : " ⚠"}`}
          </button>
        ))}
      </div>

      {tab === "analysis" ? (
        <>
          <div className="card">
            <h2>Evidence</h2>
            {decision.evidence.length ? (
              decision.evidence.map((item) => (
                <div className="evidence-item" key={item.evidence_id}>
                  <div className="row">
                    <span className="eid">{item.evidence_id}</span>
                    <Chip>{item.relevance} relevance</Chip>
                    {item.source ? <Chip tone="accent">{item.source}</Chip> : null}
                  </div>
                  <p style={{ margin: "4px 0 0" }}>{item.statement}</p>
                </div>
              ))
            ) : (
              <p className="muted">No evidence was extracted for this decision.</p>
            )}
          </div>

          <div className="card">
            <h2>Claims</h2>
            {decision.claims.length ? (
              <ul className="list">
                {decision.claims.map((claim) => (
                  <li key={claim.statement}>
                    <p style={{ margin: 0 }}>{claim.statement}</p>
                    <div className="row" style={{ marginTop: 6 }}>
                      {claim.supporting_evidence.length ? (
                        claim.supporting_evidence.map((id) => {
                          const known = evidenceById.get(id);
                          return (
                            <Chip key={id} tone={known ? "accent" : "danger"}>
                              {known ? `${id} · ${known.source ?? "no source"}` : `${id} · unresolved`}
                            </Chip>
                          );
                        })
                      ) : (
                        <Chip tone="danger">no supporting evidence</Chip>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No claims were derived.</p>
            )}
          </div>

          <div className="card">
            <h2>Alternatives</h2>
            {decision.alternatives.length ? (
              <div className="grid">
                {decision.alternatives.map((alt) => (
                  <div key={alt.name}>
                    <h3>{alt.name}</h3>
                    <p className="muted">{alt.description}</p>
                    <h4 className="diff-add" style={{ fontSize: 13 }}>
                      Advantages
                    </h4>
                    <ul>
                      {alt.advantages.length ? (
                        alt.advantages.map((a) => <li key={a}>{a}</li>)
                      ) : (
                        <li className="muted">None listed</li>
                      )}
                    </ul>
                    <h4 className="diff-remove" style={{ fontSize: 13 }}>
                      Disadvantages
                    </h4>
                    <ul>
                      {alt.disadvantages.length ? (
                        alt.disadvantages.map((d) => <li key={d}>{d}</li>)
                      ) : (
                        <li className="muted">None listed</li>
                      )}
                    </ul>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No alternatives were weighed.</p>
            )}
          </div>

          <div className="grid">
            <div className="card">
              <h2>Assumptions</h2>
              {decision.assumptions.length ? (
                <ul className="list">
                  {decision.assumptions.map((a) => (
                    <li key={a.statement}>
                      {a.statement}{" "}
                      <LevelChip level={a.confidence} kind="confidence" />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">None identified.</p>
              )}
            </div>
            <div className="card">
              <h2>Risks</h2>
              {decision.risks.length ? (
                <ul className="list">
                  {decision.risks.map((r) => (
                    <li key={r.statement}>
                      <div className="row">
                        <strong>{r.statement}</strong>
                        <LevelChip level={r.severity} kind="severity" />
                      </div>
                      {r.rationale ? (
                        <p className="muted" style={{ margin: "4px 0 0" }}>
                          {r.rationale}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">None identified.</p>
              )}
            </div>
          </div>

          <div className="card">
            <h2>Sources</h2>
            <div className="row">
              {decision.sources.length ? (
                decision.sources.map((s) => <Chip key={s}>{s}</Chip>)
              ) : (
                <span className="muted">No sources recorded.</span>
              )}
            </div>
          </div>
        </>
      ) : null}

      {tab === "provenance" ? (
        <div className="card">
          <h2>Recommendation → claims → evidence → source</h2>
          <p className="muted">
            Read straight off the stored decision. Nothing here is inferred.
          </p>
          {provenance.recommendation.claims.length ? (
            <ul className="list">
              {provenance.recommendation.claims.map((claim) => (
                <li key={claim.statement}>
                  <strong>{claim.statement}</strong>
                  {claim.evidence.map((e) => (
                    <div className="evidence-item" key={e.evidence_id}>
                      <div className="row">
                        <span className="eid">{e.evidence_id}</span>
                        {e.source ? <Chip tone="accent">{e.source}</Chip> : <Chip tone="warn">no source</Chip>}
                      </div>
                      <p style={{ margin: "4px 0 0" }}>{e.statement}</p>
                    </div>
                  ))}
                  {claim.unresolved_evidence_ids.length ? (
                    <div className="banner" style={{ marginTop: 8 }}>
                      Cites evidence this decision does not contain:{" "}
                      {claim.unresolved_evidence_ids.join(", ")}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="No claims to trace" />
          )}
          {provenance.uncited_evidence_ids.length ? (
            <p className="muted">
              Evidence held but cited by no claim:{" "}
              {provenance.uncited_evidence_ids.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {tab === "validation" ? (
        <div className="card">
          <div className="spread">
            <h2>Structural validation</h2>
            <Chip tone={validation.valid ? "ok" : "danger"}>
              {validation.valid ? "valid" : `${validation.errors.length} errors`}
            </Chip>
          </div>
          <p className="muted">
            A deterministic check that the decision is well-formed and traceable —
            not a judgement of whether it is a good decision.
          </p>
          {validation.errors.map((issue) => (
            <div className="banner" key={`${issue.code}-${issue.subject}-${issue.message}`}>
              <code>{issue.code}</code> — {issue.message}
            </div>
          ))}
          {validation.warnings.map((issue) => (
            <div className="banner warn" key={`${issue.code}-${issue.subject}-${issue.message}`}>
              <code>{issue.code}</code> — {issue.message}
            </div>
          ))}
          {validation.valid && !validation.warnings.length ? (
            <div className="banner ok">
              No structural or provenance problems found.
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
