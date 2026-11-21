import { Navigate, useSearchParams, type RouteObject } from "react-router-dom";

import { AgentConfigPage } from "../pages/AgentConfigPage";
import { AgentRunsPage } from "../pages/AgentRunsPage";
import { AgentToolsPage } from "../pages/AgentToolsPage";
import { ApisPage } from "../pages/ApisPage";
import { CasePage } from "../pages/CasePage";
import { CasesPage } from "../pages/CasesPage";
import { ExecutionPage } from "../pages/ExecutionPage";
import { DefectPage } from "../pages/DefectPage";
import { DefectsPage } from "../pages/DefectsPage";
import { ExecutionsPage } from "../pages/ExecutionsPage";
import { RunPage } from "../pages/RunPage";
import { TaskPage } from "../pages/TaskPage";
import { ModelPage } from "../pages/ModelPage";
import { ModelReviewPage } from "../pages/ModelReviewPage";
import { PeopleStatsPage } from "../pages/PeopleStatsPage";
import { PersonsPage } from "../pages/PersonsPage";
import { ReportPage } from "../pages/ReportPage";
import { ReportsPage } from "../pages/ReportsPage";
import { Placeholder } from "../pages/Placeholder";
import { SutOverviewPage } from "../pages/SutOverviewPage";
import { SutsPage } from "../pages/SutsPage";
import { UsersPage } from "../pages/UsersPage";
import { VersionPage } from "../pages/VersionPage";
import { VersionSectionPage } from "../pages/VersionSectionPage";
import { VersionsPage } from "../pages/VersionsPage";
import { Layout } from "./Layout";

/** Old case-library URL: the current system's cases, or the system list when none is named. */
function CasesRedirect() {
  const [params] = useSearchParams();
  const sut = params.get("sut") || params.get("sut_id");
  if (!sut) return <Navigate to="/suts" replace />;
  const q = new URLSearchParams();
  const version = params.get("version_id");
  if (version) q.set("version_id", version);
  const s = q.toString();
  return <Navigate to={`/suts/${sut}/cases${s ? `?${s}` : ""}`} replace />;
}

// Page codes follow the spec page list (P01–P15). Strategy and tasks have their own routes.
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/suts" replace /> },
      { path: "suts", element: <SutsPage /> }, // P01
      { path: "suts/:sutId", element: <SutOverviewPage /> },
      { path: "suts/:sutId/model", element: <ModelPage /> }, // P02 + P03 drawer
      { path: "suts/:sutId/review", element: <ModelReviewPage /> }, // model review
      { path: "suts/:sutId/apis", element: <ApisPage /> }, // P04
      { path: "suts/:sutId/versions", element: <VersionsPage /> }, // P05
      { path: "versions/:versionId/strategy", element: <VersionSectionPage section="strategy" /> },
      { path: "versions/:versionId/tasks", element: <VersionSectionPage section="tasks" /> },
      { path: "versions/:versionId", element: <VersionPage /> }, // P05 detail, P06, P09 list+coverage
      { path: "cases", element: <CasesRedirect /> },
      { path: "suts/:sutId/cases", element: <CasesPage /> },
      { path: "cases/:caseId", element: <CasePage /> }, // P09 case detail
      { path: "executions", element: <ExecutionsPage /> },
      { path: "executions/:executionId", element: <ExecutionPage /> }, // P10
      { path: "tasks/:taskId", element: <TaskPage /> }, // P08 task detail
      { path: "runs/:runId", element: <RunPage /> }, // run progress
      { path: "reports", element: <ReportsPage /> }, // P11
      { path: "reports/:reportId", element: <ReportPage /> },
      { path: "stats/people", element: <PeopleStatsPage /> }, // P13 people stats
      { path: "defects", element: <DefectsPage /> }, // P12
      { path: "defects/:defectId", element: <DefectPage /> },
      { path: "persons", element: <PersonsPage /> }, // P13 (statistics in M1-11)
      { path: "agent/config", element: <AgentConfigPage /> }, // P14
      { path: "agent/runs", element: <AgentRunsPage /> }, // P15 agent runs
      { path: "agent/tools", element: <AgentToolsPage /> }, // P15
      { path: "users", element: <UsersPage /> }, // accounts (admin)
      { path: "*", element: <Placeholder code="404" title="页面不存在" milestone="—" /> },
    ],
  },
];
