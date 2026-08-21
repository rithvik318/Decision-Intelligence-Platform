import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { WorkspaceNav } from "../components/Layout";
import { ErrorBanner, Spinner } from "../components/ui";

const STAGES = [
  "Retrieving workspace context",
  "Recalling previous decisions",
  "Extracting evidence",
  "Deriving claims",
  "Identifying assumptions and risks",
  "Evaluating alternatives",
  "Writing the recommendation",
];

export function NewDecision() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const decision = await api.createDecision(workspaceId, question, "web");
      navigate(`/w/${workspaceId}/decisions/${decision.decision_id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Ask a decision</h1>
        <p>
          The analysis runs as a sequence of model calls, so it takes a while — longer
          on a free model. You will land on the finished decision.
        </p>
      </div>
      <WorkspaceNav workspaceId={workspaceId} />

      <ErrorBanner error={error} />

      <div className="card">
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="question">Decision question</label>
            <textarea
              id="question"
              value={question}
              required
              rows={3}
              placeholder="Should we prioritise residential or commercial solar projects?"
              onChange={(e) => setQuestion(e.target.value)}
              disabled={busy}
            />
          </div>
          <button type="submit" disabled={busy || !question.trim()}>
            {busy ? "Analysing…" : "Run decision analysis"}
          </button>
        </form>
      </div>

      {busy ? (
        <div className="card">
          <Spinner label="Running the decision workflow…" />
          <ul className="list" style={{ marginTop: 12 }}>
            {STAGES.map((stage) => (
              <li key={stage} className="muted">
                {stage}
              </li>
            ))}
          </ul>
          <p className="muted" style={{ marginTop: 10 }}>
            Leave this tab open. If the provider rate-limits the request you will see
            it here rather than a silent failure.
          </p>
        </div>
      ) : null}
    </>
  );
}
