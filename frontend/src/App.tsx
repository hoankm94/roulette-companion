import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { OptimizePage } from "./pages/OptimizePage";
import { LivePlayPage } from "./pages/LivePlayPage";
import { ReplayLabPage } from "./pages/ReplayLabPage";
import { ExplorePage } from "./pages/ExplorePage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import "./styles/app.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OptimizePage />} />
          <Route path="live" element={<LivePlayPage />} />
          <Route path="replay" element={<ReplayLabPage />} />
          <Route path="explore" element={<ExplorePage />} />
          <Route path="diagnostics" element={<DiagnosticsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
