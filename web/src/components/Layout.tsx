import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">
          AI<span>·</span>KG<span>·</span>CV
        </NavLink>
        <nav className="nav">
          <NavLink to="/" end>
            Workspaces
          </NavLink>
        </nav>
      </header>
      <main>{children}</main>
    </div>
  );
}

export function WorkspaceNav({ workspaceId }: { workspaceId: string }) {
  const base = `/w/${workspaceId}`;
  return (
    <nav className="nav" style={{ marginBottom: 20 }}>
      <NavLink to={base} end>
        Knowledge
      </NavLink>
      <NavLink to={`${base}/chat`}>Chat</NavLink>
      <NavLink to={`${base}/decide`}>Ask a decision</NavLink>
      <NavLink to={`${base}/decisions`}>History</NavLink>
      <NavLink to={`${base}/compare`}>Compare</NavLink>
    </nav>
  );
}
