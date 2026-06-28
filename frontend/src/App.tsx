import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { Toaster } from "./components/Toaster";
import { isAuthenticated } from "./lib/auth";
import { AnalyticsScreen } from "./screens/AnalyticsScreen";
import { ConversationsScreen } from "./screens/ConversationsScreen";
import { CustomerProfileScreen } from "./screens/CustomerProfileScreen";
import { CustomersScreen } from "./screens/CustomersScreen";
import { LiveOpsScreen } from "./screens/LiveOpsScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { MenuManagerScreen } from "./screens/MenuManagerScreen";
import { NewOrderScreen } from "./screens/NewOrderScreen";
import { OrdersScreen } from "./screens/OrdersScreen";
import { PublicTrackingScreen } from "./screens/PublicTrackingScreen";
import { RiderTrackingScreen } from "./screens/RiderTrackingScreen";
import { RidersScreen } from "./screens/RidersScreen";
import { MarketingScreen } from "./screens/MarketingScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { TicketsScreen } from "./screens/TicketsScreen";

function Guarded({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <AppShell>{children}</AppShell>;
}

export default function App() {
  return (
    <>
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/track/:trackingToken" element={<PublicTrackingScreen />} />
      <Route path="/rider-track/:riderToken" element={<RiderTrackingScreen />} />
      <Route path="/" element={<Guarded><LiveOpsScreen /></Guarded>} />
      <Route path="/orders" element={<Guarded><OrdersScreen /></Guarded>} />
      <Route path="/customers" element={<Guarded><CustomersScreen /></Guarded>} />
      <Route path="/customers/:id" element={<Guarded><CustomerProfileScreen /></Guarded>} />
      <Route path="/new-order" element={<Guarded><NewOrderScreen /></Guarded>} />
      <Route path="/menu" element={<Guarded><MenuManagerScreen /></Guarded>} />
      <Route path="/riders" element={<Guarded><RidersScreen /></Guarded>} />
      <Route path="/conversations" element={<Guarded><ConversationsScreen /></Guarded>} />
      <Route path="/tickets" element={<Guarded><TicketsScreen /></Guarded>} />
      <Route path="/marketing" element={<Guarded><MarketingScreen /></Guarded>} />
      <Route path="/analytics" element={<Guarded><AnalyticsScreen /></Guarded>} />
      <Route path="/settings" element={<Guarded><SettingsScreen /></Guarded>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <Toaster />
    </>
  );
}
