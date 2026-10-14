import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import AppShell from "./components/AppShell";
import AuditPage from "./features/admin/AuditPage";
import HouseholdPage from "./features/profile/HouseholdPage";
import ReviewQueuePage from "./features/review/ReviewQueuePage";
import ShopPage from "./features/shop/ShopPage";
import type { Role } from "./api/types";

const HOME: Record<Role, string> = { shopper: "/shop", dietitian: "/review", founder: "/admin" };

function Only({ roles, children }: { roles: Role[]; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <Navigate to={HOME[user.role]} replace />;
  return <>{children}</>;
}

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) return null;

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={HOME[user.role]} replace /> : <LoginPage />} />
      <Route element={user ? <AppShell /> : <Navigate to="/login" replace />}>
        <Route path="/shop" element={<Only roles={["shopper"]}><ShopPage /></Only>} />
        <Route path="/household" element={<Only roles={["shopper"]}><HouseholdPage /></Only>} />
        <Route path="/review" element={<Only roles={["dietitian", "founder"]}><ReviewQueuePage /></Only>} />
        <Route path="/admin" element={<Only roles={["founder"]}><AuditPage /></Only>} />
      </Route>
      <Route path="*" element={<Navigate to={user ? HOME[user.role] : "/login"} replace />} />
    </Routes>
  );
}
