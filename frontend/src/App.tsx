import { createBrowserRouter, Navigate } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { LoginPage } from "./auth/LoginPage";
import { AppLayout } from "./layout/AppLayout";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { SearchPage } from "./pages/SearchPage";
import { AdminPage } from "./pages/AdminPage";
import { AccountPage } from "./pages/AccountPage";
import { ProjectLayout } from "./pages/project/ProjectLayout";
import { DashboardPage } from "./pages/project/DashboardPage";
import { ItemsPage } from "./pages/project/ItemsPage";
import { ItemPage } from "./pages/project/ItemPage";
import { DocumentsPage } from "./pages/project/DocumentsPage";
import { DocumentView } from "./pages/project/DocumentView";
import { StructurePage } from "./pages/project/StructurePage";
import { TraceabilityPage } from "./pages/project/TraceabilityPage";
import { ChangesPage } from "./pages/project/ChangesPage";
import { VerificationPage } from "./pages/project/VerificationPage";
import { VariantsPage } from "./pages/project/VariantsPage";
import { BaselinesPage } from "./pages/project/BaselinesPage";
import { ActivityPage } from "./pages/project/ActivityPage";
import { ReportsPage } from "./pages/project/reports/ReportsPage";
import { ReportView } from "./pages/project/reports/ReportView";
import { SettingsPage } from "./pages/project/SettingsPage";
import { NotFound } from "./components/NotFound";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthGate><AppLayout /></AuthGate>,
    children: [
      { path: "/", element: <ProjectsPage /> },
      { path: "/approvals", element: <ApprovalsPage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/admin", element: <AdminPage /> },
      { path: "/account", element: <AccountPage /> },
      {
        path: "/p/:projectKey",
        element: <ProjectLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "items", element: <ItemsPage /> },
          { path: "items/:itemKey", element: <ItemPage /> },
          { path: "documents", element: <DocumentsPage /> },
          { path: "documents/:specKey", element: <DocumentView /> },
          { path: "structure", element: <StructurePage /> },
          { path: "traceability", element: <TraceabilityPage /> },
          { path: "changes", element: <ChangesPage /> },
          { path: "verification", element: <VerificationPage /> },
          { path: "variants", element: <VariantsPage /> },
          { path: "baselines", element: <BaselinesPage /> },
          { path: "reports", element: <ReportsPage /> },
          { path: "reports/:reportId", element: <ReportView /> },
          { path: "activity", element: <ActivityPage /> },
          { path: "settings", element: <SettingsPage /> },
        ],
      },
      { path: "/home", element: <Navigate to="/" replace /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);
