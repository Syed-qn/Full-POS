import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useParams, useSearchParams } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { NoAccessScreen } from "./components/NoAccessScreen";
import { Toaster } from "./components/Toaster";
import { isAuthenticated } from "./lib/auth";
import {
  canAccess,
  getRoleChrome,
  getRoleHomePath,
  getSessionRole,
  isCashierRole,
  isFullBleedPath,
  isWaiterRole,
} from "./lib/navAccess";
import {
  readCachedOnboardingComplete,
  resolveOnboardingComplete,
} from "./lib/onboardingGate";
import { AnalyticsScreen } from "./screens/AnalyticsScreen";
import { ForecastScreen } from "./screens/ForecastScreen";
import { BranchOpsScreen } from "./screens/BranchOpsScreen";
import { ConversationsScreen } from "./screens/ConversationsScreen";
import { CustomerProfileScreen } from "./screens/CustomerProfileScreen";
import { CustomersScreen } from "./screens/CustomersScreen";
import { InventoryScreen } from "./screens/InventoryScreen";
import { KdsScreen } from "./screens/KdsScreen";
import { KitchensScreen } from "./screens/KitchensScreen";
import { ManagerManagementScreen } from "./screens/ManagerManagementScreen";
import { LiveOpsScreen } from "./screens/LiveOpsScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { MenuManagerScreen } from "./screens/MenuManagerScreen";
import { OnboardingScreen } from "./screens/OnboardingScreen";
import { NewOrderScreen } from "./screens/NewOrderScreen";
import { OrdersScreen } from "./screens/OrdersScreen";
import { PublicTrackingScreen } from "./screens/PublicTrackingScreen";
import { ReportsScreen } from "./screens/ReportsScreen";
import { RiderTrackingScreen } from "./screens/RiderTrackingScreen";
import { RidersScreen } from "./screens/RidersScreen";
import { MarketingScreen } from "./screens/MarketingScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { StaffScreen } from "./screens/StaffScreen";
import { TicketsScreen } from "./screens/TicketsScreen";
import { CouponsScreen } from "./screens/CouponsScreen";
import { PaymentsScreen } from "./screens/PaymentsScreen";
import { ChannelsScreen } from "./screens/ChannelsScreen";
import { PublicStoreScreen } from "./screens/PublicStoreScreen";
import { ReliabilityScreen } from "./screens/ReliabilityScreen";
import { ComplianceScreen } from "./screens/ComplianceScreen";
import { AiInsightsScreen } from "./screens/AiInsightsScreen";
import { FloorPlanScreen } from "./screens/FloorPlanScreen";
import { WaiterFloorScreen } from "./screens/WaiterFloorScreen";
import { WaiterOrderScreen } from "./screens/WaiterOrderScreen";
import { OrderDetailScreen } from "./screens/OrderDetailScreen";
import { CheckoutScreen } from "./screens/CheckoutScreen";
import { CashierFloorScreen } from "./screens/CashierFloorScreen";
import { CashierDeliveryScreen } from "./screens/CashierDeliveryScreen";
import { CashierTakeawayScreen } from "./screens/CashierTakeawayScreen";
import { CashierWhatsappScreen } from "./screens/CashierWhatsappScreen";
import { RiderAppScreen } from "./screens/RiderAppScreen";

/**
 * /floor serves two audiences: waiters get the full-bleed dark floor display,
 * managers/cashiers keep the admin floor plan with its transfer/merge tooling.
 */
function FloorRoute() {
  return isWaiterRole() ? <WaiterFloorScreen /> : <FloorPlanScreen />;
}

/** Waiters and cashiers get the dark order terminal; everyone else keeps the POS screen.
 *
 * The terminal stays mounted across channel tabs (they share the /new-order route),
 * so switching Home Delivery → Take Away would otherwise carry the cart, discount,
 * and customer over. Key the screen on the channel (and any reopened order id) to
 * force a fresh till per channel — while still remounting to load an existing tab. */
function NewOrderRoute() {
  const [params] = useSearchParams();
  // ?split carries a unique token per press, and it MUST be part of the key: a
  // split targets the same table as the tab already on screen, so without it the
  // key is unchanged, the screen never remounts, and the till stays pointed at the
  // bill it just created — every further "Split bill" would append to bill 2
  // instead of opening bill 3. Splits have to be unlimited.
  const key = `${params.get("type") ?? "dine_in"}:${params.get("order") ?? params.get("table") ?? "new"}:${params.get("split") ?? ""}`;
  return isWaiterRole() || isCashierRole() ? (
    <WaiterOrderScreen key={key} />
  ) : (
    <NewOrderScreen key={key} />
  );
}

/** Redirect an old /customers/:id profile link to the renamed path, keeping the id. */
function RedirectCustomerProfile() {
  const { id } = useParams();
  return <Navigate to={`/customer-management/${id ?? ""}`} replace />;
}

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

  // Soft role gate: keep shell chrome; show friendly no-access (public routes are unguarded).
  const role = getSessionRole();
  if (!canAccess(loc.pathname, role)) {
    // Chrome-free roles (waiter/cashier/kitchen) have no sidebar to escape a
    // dead-end "No access" wall, and each owns a single surface. So bounce them
    // to THEIR home on ANY denied route — a waiter who lands on /floor (or "/")
    // is sent to /waiter/floor. Sidebar roles (staff/rider) keep the friendly
    // No-access screen since they can navigate away from it; everyone still gets
    // bounced off the bare root.
    const home = getRoleHomePath(role);
    const chromeFree = !getRoleChrome(role).showSidebar;
    if (home !== "/" && (loc.pathname === "/" || chromeFree)) {
      return <Navigate to={home} replace />;
    }
    return (
      <AppShell>
        <NoAccessScreen />
      </AppShell>
    );
  }

  // The kitchen board runs full-bleed for EVERYONE, not just a kitchen login.
  // It is mounted on a wall screen and read across a hot line: sidebar and top
  // bar cost a third of the width and offer nothing a cook can act on. It
  // carries its own header strip — brand, kitchen picker, sign out — so
  // dropping the shell leaves no dead end.
  if (isFullBleedPath(loc.pathname)) return <>{children}</>;

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
      <Route path="/order/:slug" element={<PublicStoreScreen />} />
      <Route path="/" element={<Guarded><LiveOpsScreen /></Guarded>} />
      <Route path="/floor" element={<Guarded><FloorRoute /></Guarded>} />
      <Route path="/waiter/floor" element={<Guarded><FloorRoute /></Guarded>} />
      <Route path="/waiter/new-order" element={<Guarded><NewOrderRoute /></Guarded>} />
      <Route path="/cashier/floor" element={<Guarded><CashierFloorScreen /></Guarded>} />
      <Route path="/cashier/takeaway" element={<Guarded><CashierTakeawayScreen /></Guarded>} />
      <Route path="/cashier/delivery" element={<Guarded><CashierDeliveryScreen /></Guarded>} />
      <Route path="/cashier/whatsapp" element={<Guarded><CashierWhatsappScreen /></Guarded>} />
      <Route path="/cashier/new-order" element={<Guarded><NewOrderRoute /></Guarded>} />
      <Route path="/orders" element={<Guarded><OrdersScreen /></Guarded>} />
      <Route
        path="/orders/:id/pay"
        element={
          <Guarded>
            <CheckoutScreen />
          </Guarded>
        }
      />
      <Route
        path="/orders/:id"
        element={
          <Guarded>
            <OrderDetailScreen />
          </Guarded>
        }
      />
      <Route path="/customer-management" element={<Guarded><CustomersScreen /></Guarded>} />
      <Route path="/customer-management/:id" element={<Guarded><CustomerProfileScreen /></Guarded>} />
      {/* Old /customers paths kept as redirects for existing links/bookmarks. */}
      <Route path="/customers" element={<Navigate to="/customer-management" replace />} />
      <Route path="/customers/:id" element={<RedirectCustomerProfile />} />
      <Route path="/new-order" element={<Guarded><NewOrderRoute /></Guarded>} />
      <Route path="/menu" element={<Guarded><MenuManagerScreen /></Guarded>} />
      <Route path="/kds" element={<Guarded><KdsScreen /></Guarded>} />
      <Route path="/kds/:stationId" element={<Guarded><KdsScreen /></Guarded>} />
      <Route path="/kitchens" element={<Guarded><KitchensScreen /></Guarded>} />
      <Route path="/inventory" element={<Guarded><InventoryScreen /></Guarded>} />
      <Route path="/branches" element={<Guarded><BranchOpsScreen /></Guarded>} />
      <Route path="/rider-management" element={<Guarded><RidersScreen /></Guarded>} />
      <Route path="/riders" element={<Navigate to="/rider-management" replace />} />
      <Route path="/rider-app" element={<RiderAppScreen />} />
      <Route path="/conversations" element={<Guarded><ConversationsScreen /></Guarded>} />
      <Route path="/tickets" element={<Guarded><TicketsScreen /></Guarded>} />
      <Route path="/coupons" element={<Guarded><CouponsScreen /></Guarded>} />
      <Route path="/payments" element={<Guarded><PaymentsScreen /></Guarded>} />
      <Route path="/channels" element={<Guarded><ChannelsScreen /></Guarded>} />
      <Route path="/reliability" element={<Guarded><ReliabilityScreen /></Guarded>} />
      <Route path="/compliance" element={<Guarded><ComplianceScreen /></Guarded>} />
      <Route path="/ai" element={<Guarded><AiInsightsScreen /></Guarded>} />
      <Route path="/waiter-management" element={<Guarded><StaffScreen managedRole="waiter" /></Guarded>} />
      <Route path="/cashier-management" element={<Guarded><StaffScreen managedRole="cashier" /></Guarded>} />
      <Route path="/kitchen-staff" element={<Guarded><StaffScreen managedRole="kitchen" /></Guarded>} />
      <Route path="/manager-management" element={<Guarded><ManagerManagementScreen /></Guarded>} />
      {/* Old /staff path kept as a redirect for existing links/bookmarks. */}
      <Route path="/staff" element={<Navigate to="/waiter-management" replace />} />
      <Route path="/marketing" element={<Guarded><MarketingScreen /></Guarded>} />
      <Route path="/analytics" element={<Guarded><AnalyticsScreen /></Guarded>} />
      <Route path="/forecast" element={<Guarded><ForecastScreen /></Guarded>} />
      {/* Old /predictions path kept as a redirect for existing links/bookmarks. */}
      <Route path="/predictions" element={<Navigate to="/forecast" replace />} />
      <Route path="/reports" element={<Guarded><ReportsScreen /></Guarded>} />
      <Route path="/settings" element={<Guarded><SettingsScreen /></Guarded>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <Toaster />
    </>
  );
}
