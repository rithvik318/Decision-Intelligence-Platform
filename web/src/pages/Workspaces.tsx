import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Chip, Empty, ErrorBanner, Spinner, formatDate } from "../components/ui";
import { useAsync } from "../hooks";

export function Workspaces() {
  const { data, loading, error, reload } = useAsync(() => api.listWorkspaces(), []);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await api.createWorkspace(name, description);
      setName("");
      setDescription("");
      reload();
    } catch (err) {
      setCreateError(err);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Workspaces</h1>
        <p>
          A workspace is one decision domain — its documents, its knowledge graph and
          its decision history are isolated from every other workspace.
        </p>
      </div>

      <div className="card">
        <h2>New workspace</h2>
        <ErrorBanner error={createError} />
        <form onSubmit={create}>
          <div className="field">
            <label htmlFor="ws-name">Name</label>
            <input
              id="ws-name"
              type="text"
              value={name}
              required
              placeholder="Solar Market Analysis"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="ws-desc">What decision is this about?</label>
            <input
              id="ws-desc"
              type="text"
              value={description}
              placeholder="Should we enter the German solar market?"
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <button type="submit" disabled={creating || !name.trim()}>
            {creating ? "Creating…" : "Create workspace"}
          </button>
        </form>
      </div>

      <ErrorBanner error={error} />
      {loading ? (
        <Spinner label="Loading workspaces…" />
      ) : !data?.length ? (
        <Empty title="No workspaces yet">
          <p>Create one above, then add the documents your decision rests on.</p>
        </Empty>
      ) : (
        <div className="grid">
          {data.map((workspace) => (
            <div className="card" key={workspace.workspace_id}>
              <div className="spread">
                <h2 style={{ marginBottom: 4 }}>
                  <Link to={`/w/${workspace.workspace_id}`}>{workspace.name}</Link>
                </h2>
                {workspace.graph_built ? (
                  <Chip tone="ok">graph built</Chip>
                ) : (
                  <Chip>no graph</Chip>
                )}
              </div>
              <p className="muted">{workspace.description || "No description."}</p>
              <div className="row">
                <Chip tone="accent">
                  {workspace.document_count}{" "}
                  {workspace.document_count === 1 ? "document" : "documents"}
                </Chip>
                <span className="muted">
                  knowledge updated {formatDate(workspace.knowledge_updated_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
