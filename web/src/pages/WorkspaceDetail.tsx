import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { WorkspaceNav } from "../components/Layout";
import { Chip, Empty, ErrorBanner, Spinner, formatDate } from "../components/ui";
import { useAsync } from "../hooks";

export function WorkspaceDetail() {
  const { workspaceId = "" } = useParams();
  const { data, loading, error, reload } = useAsync(
    () => api.getWorkspace(workspaceId),
    [workspaceId],
  );

  const [fileName, setFileName] = useState("");
  const [content, setContent] = useState("");
  const [buildGraph, setBuildGraph] = useState(false);
  const [busy, setBusy] = useState<null | "ingest" | "graph">(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function ingest(event: React.FormEvent) {
    event.preventDefault();
    setBusy("ingest");
    setActionError(null);
    setNotice(null);
    try {
      const result = await api.ingestText(
        workspaceId,
        [{ content, file_name: fileName.trim() || "pasted-note.md" }],
        buildGraph,
      );
      setNotice(
        `Ingested ${result.documents_ingested} document into ${result.dataset}.` +
          (result.graph_built ? " Graph enrichment ran." : ""),
      );
      setContent("");
      setFileName("");
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  }

  async function enrich() {
    setBusy("graph");
    setActionError(null);
    setNotice(null);
    try {
      await api.buildGraph(workspaceId);
      setNotice("Graph enrichment finished.");
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Spinner label="Loading workspace…" />;
  if (error) return <ErrorBanner error={error} />;
  if (!data) return null;

  return (
    <>
      <div className="page-head">
        <h1>{data.name}</h1>
        <p>{data.description || "No description."}</p>
      </div>
      <WorkspaceNav workspaceId={workspaceId} />

      {notice ? <div className="banner ok">{notice}</div> : null}
      <ErrorBanner error={actionError} />

      <div className="card">
        <div className="spread">
          <h2>Knowledge</h2>
          <div className="row">
            {data.graph_built ? (
              <Chip tone="ok">graph built</Chip>
            ) : (
              <Chip tone="warn">graph not built</Chip>
            )}
            <button
              className="secondary"
              onClick={enrich}
              disabled={busy !== null || data.document_count === 0}
            >
              {busy === "graph" ? "Enriching…" : "Build graph"}
            </button>
          </div>
        </div>
        <p className="muted">
          Ingestion indexes chunks immediately and costs no model calls. Graph
          enrichment extracts entities and relationships with the LLM — slower, and
          metered — so it is a separate step.
        </p>
        {busy === "graph" ? <Spinner label="Running graph enrichment. This can take minutes on a free model…" /> : null}

        {data.documents.length === 0 ? (
          <Empty title="No documents yet">
            <p>Paste a document below to give this workspace something to reason over.</p>
          </Empty>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Source</th>
                  <th>Ingested</th>
                </tr>
              </thead>
              <tbody>
                {data.documents.map((doc) => (
                  <tr key={`${doc.file_name}-${doc.ingested_at}`}>
                    <td>{doc.file_name}</td>
                    <td>{doc.document_type}</td>
                    <td>{doc.source}</td>
                    <td>{formatDate(doc.ingested_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Add a document</h2>
        <form onSubmit={ingest}>
          <div className="field">
            <label htmlFor="doc-name">File name</label>
            <input
              id="doc-name"
              type="text"
              value={fileName}
              placeholder="market_overview.md"
              onChange={(e) => setFileName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="doc-content">Content</label>
            <textarea
              id="doc-content"
              value={content}
              required
              rows={8}
              placeholder="Paste the document text…"
              onChange={(e) => setContent(e.target.value)}
            />
          </div>
          <div className="field checkbox">
            <input
              id="build-graph"
              type="checkbox"
              checked={buildGraph}
              onChange={(e) => setBuildGraph(e.target.checked)}
            />
            <label htmlFor="build-graph" style={{ margin: 0 }}>
              Run graph enrichment now (slower, uses the LLM)
            </label>
          </div>
          <button type="submit" disabled={busy !== null || !content.trim()}>
            {busy === "ingest" ? "Ingesting…" : "Ingest document"}
          </button>
        </form>
      </div>
    </>
  );
}
