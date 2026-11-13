import {
  useState,
  useEffect,
} from "react";

import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
} from "react-router-dom";

import {
  AuthProvider,
  useAuth,
} from "./context/AuthContext";

import {
  ToastProvider,
} from "./context/ToastContext";

import {
  NotificationProvider,
} from "./context/NotificationContext";

import AppLayout from "./components/layout/AppLayout";
import SplashScreen from "./components/SplashScreen";

import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";

import DeploymentRequests from "./pages/DeploymentRequests";
import DeploymentDetail from "./pages/DeploymentDetail";

import AccessRequests from "./pages/AccessRequests";
import AccessDetail from "./pages/AccessDetail";

import AwsIssues from "./pages/AwsIssues";
import AwsIssueDetail from "./pages/AwsIssueDetail";

import UserManagement from "./pages/UserManagement";
import UserProfileView from "./pages/UserProfileView";
import Applications from "./pages/Applications";
import Profile from "./pages/Profile";


/* =========================================================
   PROTECTED ROUTE
   ========================================================= */

function ProtectedRoute({
  children,
  adminOnly = false,
  devOpsOnly = false,
}) {
  const {
    user,
    loading,
    isAdmin,
  } = useAuth();

  /* Authentication is still loading */
  if (loading) {
    return (
      <div className="app-loading-screen">
        <div className="app-loading-bg" />
        <div className="app-loading-content">
          <div className="app-loading-logo">OPS</div>
          <div className="app-loading-title">OPSFlow</div>
          <div className="app-loading-bar">
            <div className="app-loading-bar-fill" />
          </div>
          <p className="app-loading-text">Loading your workspace…</p>
        </div>
      </div>
    );
  }

  /* User is not logged in */
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  /* Admin-only page */
  if (adminOnly && !isAdmin) {
    return <Navigate to="/" replace />;
  }

  /* DevOps-only page */
  if (devOpsOnly && user.role !== "DevOps") {
    return <Navigate to="/" replace />;
  }

  return children;
}


/* =========================================================
   SPLASH GATE
   Shows the OPSFlow splash animation once when the app opens,
   then hands off to the router (which decides login vs
   dashboard based on auth state).
   ========================================================= */

function SplashGate({ children }) {
  // SPEED: the splash used to block the app for a fixed 2.2 s on every load.
  // Now it is a short flash only on the first open of a browser tab; reloads
  // skip it. (While the login check is still running, ProtectedRoute shows the
  // same splash anyway, so nothing un-styled is ever visible.)
  const [showSplash, setShowSplash] = useState(() => {
    try {
      return !sessionStorage.getItem("opsflow-splash-seen");
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (!showSplash) return undefined;
    try {
      sessionStorage.setItem("opsflow-splash-seen", "1");
    } catch {
      /* ignore */
    }
    const timer = setTimeout(() => {
      setShowSplash(false);
    }, 500);

    return () => clearTimeout(timer);
  }, [showSplash]);

  if (showSplash) {
    return <SplashScreen />;
  }

  return children;
}


/* =========================================================
   APPLICATION ROUTES
   ========================================================= */

function AppRoutes() {
  return (
    <Routes>

      {/* ===================================================
          LOGIN
          =================================================== */}

      <Route
        path="/login"
        element={<Login />}
      />


      {/* ===================================================
          PROTECTED APPLICATION
          =================================================== */}

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >

        {/* =================================================
            DASHBOARD
            ================================================= */}

        <Route
          index
          element={<Dashboard />}
        />


        {/* =================================================
            DEPLOYMENTS
            ================================================= */}

        <Route
          path="deployments"
          element={<DeploymentRequests />}
        />

        <Route
          path="deployments/:id"
          element={<DeploymentDetail />}
        />


        {/* =================================================
            ACCESS REQUESTS
            ================================================= */}

        <Route
          path="access"
          element={<AccessRequests />}
        />

        <Route
          path="access/:id"
          element={<AccessDetail />}
        />


        {/* =================================================
            AWS ISSUES
            DEVOPS + DEVOPS ADMIN ONLY
            ================================================= */}

        <Route
          path="aws-issues"
          element={
            <ProtectedRoute devOpsOnly>
              <AwsIssues />
            </ProtectedRoute>
          }
        />

        <Route
          path="aws-issues/:id"
          element={
            <ProtectedRoute devOpsOnly>
              <AwsIssueDetail />
            </ProtectedRoute>
          }
        />


        {/* =================================================
            PROFILE
            ================================================= */}

        <Route
          path="profile"
          element={<Profile />}
        />


        {/* =================================================
            USER MANAGEMENT
            ADMIN ONLY
            ================================================= */}

        <Route
          path="users"
          element={
            <ProtectedRoute adminOnly>
              <UserManagement />
            </ProtectedRoute>
          }
        />

        {/* =================================================
            APPLICATIONS
            ADMIN ONLY — add new applications
            ================================================= */}

        <Route
          path="users/:id"
          element={
            <ProtectedRoute adminOnly>
              <UserProfileView />
            </ProtectedRoute>
          }
        />

        <Route
          path="applications"
          element={
            <ProtectedRoute adminOnly>
              <Applications />
            </ProtectedRoute>
          }
        />

      </Route>


      {/* ===================================================
          UNKNOWN ROUTES
          =================================================== */}

      <Route
        path="*"
        element={<Navigate to="/" replace />}
      />

    </Routes>
  );
}


/* =========================================================
   APP
   ========================================================= */

export default function App() {
  return (
    <BrowserRouter>

      <ToastProvider>

        <AuthProvider>

          <NotificationProvider>

            <SplashGate>
              <AppRoutes />
            </SplashGate>

          </NotificationProvider>

        </AuthProvider>

      </ToastProvider>

    </BrowserRouter>
  );
}