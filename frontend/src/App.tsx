import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { isAuthenticated } from "./lib/auth";
import { AnalyticsScreen } from "./screens/AnalyticsScreen";
import { ConversationsScreen } from "./screens/ConversationsScreen";
import { LiveOpsScreen } from "./screens/LiveOpsScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { MenuManagerScreen } from "./screens/MenuManagerScreen";
import { OrdersScreen } from "./screens/OrdersScreen";
import { RidersScreen } from "./screens/RidersScreen";
import { SettingsScreen } from "./screens/SettingsScreen";

function Guarded({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <AppShell>{children}</AppShell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/" element={<Guarded><LiveOpsScreen /></Guarded>} />
      <Route path="/orders" element={<Guarded><OrdersScreen /></Guarded>} />
      <Route path="/menu" element={<Guarded><MenuManagerScreen /></Guarded>} />
      <Route path="/riders" element={<Guarded><RidersScreen /></Guarded>} />
      <Route path="/conversations" element={<Guarded><ConversationsScreen /></Guarded>} />
      <Route path="/analytics" element={<Guarded><AnalyticsScreen /></Guarded>} />
      <Route path="/settings" element={<Guarded><SettingsScreen /></Guarded>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
