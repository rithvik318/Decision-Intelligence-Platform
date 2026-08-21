import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { WorkspaceNav } from "../components/Layout";
import { Chip, Empty, ErrorBanner, Spinner } from "../components/ui";
import type { ChatAnswer } from "../types";

export function Chat() {
  const { workspaceId = "" } = useParams();
  const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState<ChatAnswer | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setAnswer(null);
    setAsked(message);
    try {
      setAnswer(await api.chat(workspaceId, message, "web"));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Ask the knowledge base</h1>
        <p>
          A direct question against this workspace's documents. For a recommendation
          with evidence, assumptions and alternatives, use Ask a decision instead.
        </p>
      </div>
      <WorkspaceNav workspaceId={workspaceId} />

      <div className="card">
        <form onSubmit={ask}>
          <div className="field">
            <label htmlFor="q">Question</label>
            <input
              id="q"
              type="text"
              value={message}
              required
              placeholder="How do feed-in tariffs affect rooftop projects?"
              onChange={(e) => setMessage(e.target.value)}
            />
          </div>
          <button type="submit" disabled={busy || !message.trim()}>
            {busy ? "Asking…" : "Ask"}
          </button>
        </form>
      </div>

      <ErrorBanner error={error} />
      {busy ? <Spinner label="Retrieving context and generating an answer…" /> : null}

      {answer ? (
        <div className="card">
          <h2>{asked}</h2>
          <p>{answer.answer}</p>
          <div className="row">
            <Chip tone="accent">{answer.retrieval.semantic_hits} semantic</Chip>
            <Chip tone="accent">{answer.retrieval.graph_hits} graph</Chip>
            <Chip tone="accent">{answer.retrieval.memory_hits} memory</Chip>
          </div>
          {answer.retrieval.graph_hits === 0 ? (
            <p className="muted" style={{ marginTop: 10 }}>
              No graph hits. If you have not run graph enrichment for this workspace,
              answers rest on semantic retrieval alone.
            </p>
          ) : null}
          {answer.sources.length ? (
            <>
              <h3 style={{ marginTop: 14 }}>Sources</h3>
              <div className="row">
                {answer.sources.map((source) => (
                  <Chip key={source}>{source}</Chip>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ) : !busy && !error ? (
        <Empty title="No question asked yet">
          <p>Ask something above to see an answer grounded in this workspace.</p>
        </Empty>
      ) : null}
    </>
  );
}
