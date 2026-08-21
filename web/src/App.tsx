import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Chat } from "./pages/Chat";
import { Compare } from "./pages/Compare";
import { DecisionDetail } from "./pages/DecisionDetail";
import { DecisionHistory } from "./pages/DecisionHistory";
import { NewDecision } from "./pages/NewDecision";
import { WorkspaceDetail } from "./pages/WorkspaceDetail";
import { Workspaces } from "./pages/Workspaces";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Workspaces />} />
        <Route path="/w/:workspaceId" element={<WorkspaceDetail />} />
        <Route path="/w/:workspaceId/chat" element={<Chat />} />
        <Route path="/w/:workspaceId/decide" element={<NewDecision />} />
        <Route path="/w/:workspaceId/decisions" element={<DecisionHistory />} />
        <Route
          path="/w/:workspaceId/decisions/:decisionId"
          element={<DecisionDetail />}
        />
        <Route path="/w/:workspaceId/compare" element={<Compare />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
