import { Routes, Route, useParams } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ProjectProvider } from "@/context/ProjectContext";
import { Dashboard } from "@/pages/Dashboard";
import { SuiteList, SuiteDetail } from "@/pages/SuiteDetail";
import { RunMonitor } from "@/pages/RunMonitor";
import { RunResults } from "@/pages/RunResults";
import { CaseDetail } from "@/pages/CaseDetail";
import { ComparisonPage } from "@/pages/ComparisonPage";
import { PlaygroundPage } from "@/pages/PlaygroundPage";
import { BatchMonitor } from "@/pages/BatchMonitor";
import { BatchComparePage } from "@/pages/BatchComparePage";
import { OracleReviewPage } from "@/pages/OracleReviewPage";

function RunMonitorPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  return <RunMonitor runId={runId} />;
}

function RunResultsPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  return <RunResults runId={runId} />;
}

function BatchMonitorPage() {
  const { batchId = "" } = useParams<{ batchId: string }>();
  return <BatchMonitor batchId={batchId} />;
}

export default function App() {
  return (
    <ProjectProvider>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="suites" element={<SuiteList />} />
        <Route path="suites/:suiteId" element={<SuiteDetail />} />
        <Route path="runs/:runId" element={<RunResultsPage />} />
        <Route path="runs/:runId/monitor" element={<RunMonitorPage />} />
        <Route path="runs/:runId/cases/:caseId" element={<CaseDetail />} />
        <Route path="batch/:batchId/monitor" element={<BatchMonitorPage />} />
        <Route path="batch/:batchId/compare" element={<BatchComparePage />} />
        <Route path="compare" element={<ComparisonPage />} />
        <Route path="suites/:suiteId/playground" element={<PlaygroundPage />} />
        <Route path="oracle-review" element={<OracleReviewPage />} />
        <Route path="suites/:suiteId/oracle-review" element={<OracleReviewPage />} />
        <Route path="*" element={
          <div className="p-6 text-sm text-gray-400">Page not found.</div>
        } />
      </Route>
    </Routes>
    </ProjectProvider>
  );
}
