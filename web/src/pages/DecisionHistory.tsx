import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { WorkspaceNav } from "../components/Layout";
import { Chip, Empty, ErrorBanner, Spinner, formatDate } from "../components/ui";
import { useAsync } from "../hooks";

export function DecisionHistory() {
  const { workspaceId = "" } = useParams();
  const { data, loading, error } = useAsync(
    () => api.listDecisions(workspaceId),
    [workspaceId],
  );

  return (
    <>
      <div className="page-head">
        <h1>Decision history</h1>
        <p>Every decision recorded in this workspace, newest first.</p>
      </div>
      <WorkspaceNav workspaceId={workspaceId} />

      <ErrorBanner error={error} />
      {loading ? (
        <Spinner label="Loading decisions…" />
      ) : !data?.length ? (
        <Empty title="No decisions yet">
          <p>
            Use <Link to={`/w/${workspaceId}/decide`}>Ask a decision</Link> to record
            the first one.
          </p>
        </Empty>
      ) : (
        <div className="card">
          <ul className="list">
            {data.map((decision) => (
              <li key={decision.decision_id}>
                <div className="spread">
                  <div>
                    <Link to={`/w/${workspaceId}/decisions/${decision.decision_id}`}>
                      <strong>{decision.question}</strong>
                    </Link>
                    <p className="muted" style={{ margin: "4px 0 0" }}>
                      {decision.recommendation.statement}
                    </p>
                  </div>
                  <div className="row">
                    <Chip tone={decision.status === "reassessed" ? "accent" : "neutral"}>
                      {decision.status}
                    </Chip>
                    <span className="muted">{formatDate(decision.created_at)}</span>
                  </div>
                </div>
                {decision.supersedes ? (
                  <p className="muted" style={{ margin: "6px 0 0" }}>
                    Supersedes{" "}
                    <Link to={`/w/${workspaceId}/decisions/${decision.supersedes}`}>
                      an earlier decision
                    </Link>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
