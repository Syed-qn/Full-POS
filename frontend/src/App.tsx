import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { Toaster } from "./components/Toaster";
import { isAuthenticated } from "./lib/auth";
import {
  readCachedOnboardingComplete,
  resolveOnboardingComplete,
} from "./lib/onboardingGate";
import { AnalyticsScreen } from "./screens/AnalyticsScreen";
import { BranchOpsScreen } from "./screens/BranchOpsScreen";
import { ConversationsScreen } from "./screens/ConversationsScreen";
import { CustomerProfileScreen } from "./screens/CustomerProfileScreen";
import { CustomersScreen } from "./screens/CustomersScreen";
import { InventoryScreen } from "./screens/InventoryScreen";
import { KdsScreen } from "./screens/KdsScreen";
import { LiveOpsScreen } from "./screens/LiveOpsScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { MenuManagerScreen } from "./screens/MenuManagerScreen";
import { OnboardingScreen } from "./screens/OnboardingScreen";
import { NewOrderScreen } from "./screens/NewOrderScreen";
import { OrdersScreen } from "./screens/OrdersScreen";
import { PublicTrackingScreen } from "./screens/PublicTrackingScreen";
import { RiderTrackingScreen } from "./screens/RiderTrackingScreen";
import { RidersScreen } from "./screens/RidersScreen";
import { MarketingScreen } from "./screens/MarketingScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { StaffScreen } from "./screens/StaffScreen";
import { TicketsScreen } from "./screens/TicketsScreen";
import { CouponsScreen } from "./screens/CouponsScreen";

function Guarded({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  const [onboardingOk, setOnboardingOk] = useState<boolean | null>(() =>
    isAuthenticated() ? readCachedOnboardingComplete() : null,
  );

  useEffect(() => {
    if (!isAuthenticated()) return;
    // Only block the first paint when we have no cached value yet.
    if (readCachedOnboardingComplete() !== null) {
      setOnboardingOk(readCachedOnboardingComplete());
      return;
    }
    resolveOnboardingComplete().then(setOnboardingOk);
  }, []);

  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  if (onboardingOk === false && loc.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }
  if (onboardingOk === null) return null;
  return <AppShell>{children}</AppShell>;
}

function OnboardingRoute() {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <OnboardingScreen />;
}

export default function App() {
  return (
    <>
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/onboarding" element={<OnboardingRoute />} />
      <Route path="/track/:trackingToken" element={<PublicTrackingScreen />} />
      <Route path="/rider-track/:riderToken" element={<RiderTrackingScreen />} />
      <Route path="/" element={<Guarded><LiveOpsScreen /></Guarded>} />
      <Route path="/orders" element={<Guarded><OrdersScreen /></Guarded>} />
      <Route path="/customers" element={<Guarded><CustomersScreen /></Guarded>} />
      <Route path="/customers/:id" element={<Guarded><CustomerProfileScreen /></Guarded>} />
      <Route path="/new-order" element={<Guarded><NewOrderScreen /></Guarded>} />
      <Route path="/menu" element={<Guarded><MenuManagerScreen /></Guarded>} />
      <Route path="/kds/:stationId" element={<Guarded><KdsScreen /></Guarded>} />
      <Route path="/inventory" element={<Guarded><InventoryScreen /></Guarded>} />
      <Route path="/branches" element={<Guarded><BranchOpsScreen /></Guarded>} />
      <Route path="/riders" element={<Guarded><RidersScreen /></Guarded>} />
      <Route path="/conversations" element={<Guarded><ConversationsScreen /></Guarded>} />
      <Route path="/tickets" element={<Guarded><TicketsScreen /></Guarded>} />
      <Route path="/coupons" element={<Guarded><CouponsScreen /></Guarded>} />
      <Route path="/staff" element={<Guarded><StaffScreen /></Guarded>} />
      <Route path="/marketing" element={<Guarded><MarketingScreen /></Guarded>} />
      <Route path="/analytics" element={<Guarded><AnalyticsScreen /></Guarded>} />
      <Route path="/settings" element={<Guarded><SettingsScreen /></Guarded>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <Toaster />
    </>
  );
}
