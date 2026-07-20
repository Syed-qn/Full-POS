import { useQuery } from "@tanstack/react-query";
import { listCoupons } from "../couponsApi";
import { listCustomers, getCustomerProfile } from "../customerApi";
import { fetchConversations, fetchMessages } from "../conversationsApi";
import {
  DETAIL_INCLUDE_BY_TAB,
  fetchOrderDetail,
} from "../orderDetailApi";
import { fetchOrders, type FetchOrdersOpts } from "../ordersApi";
import { fetchRiders } from "../ridersApi";
import { listTickets } from "../ticketsApi";
import { getWallet, getWalletEntries } from "../walletApi";

const POLL_MS = 12_000;
const LIVE_OPS_MS = 4_000;
const DETAIL_STALE_MS = 10_000;

export type OrdersListFilters = FetchOrdersOpts & {
  page?: number;
};

function pollWhenVisible(intervalMs: number) {
  return () =>
    typeof document !== "undefined" && document.visibilityState === "visible"
      ? intervalMs
      : false;
}

function ordersFetchOpts(filters: OrdersListFilters): FetchOrdersOpts {
  const { page = 1, limit = 50, ...rest } = filters;
  const lim = limit ?? 50;
  return {
    ...rest,
    limit: lim,
    offset: (page - 1) * lim,
  };
}

export function useOrdersQuery(filters: OrdersListFilters = {}) {
  const previewBatch = filters.previewBatch !== false;
  const pollMs = previewBatch ? POLL_MS : LIVE_OPS_MS;
  return useQuery({
    queryKey: ["orders", "list", filters],
    queryFn: () => fetchOrders(ordersFetchOpts(filters)),
    staleTime: pollMs,
    refetchInterval: pollWhenVisible(pollMs),
    placeholderData: (prev) => prev,
  });
}

export function useLiveOpsOrdersQuery() {
  return useOrdersQuery({ previewBatch: false });
}

export type OrderDetailTab = keyof typeof DETAIL_INCLUDE_BY_TAB;

export function useOrderDetailQuery(
  orderId: number | null,
  tab: OrderDetailTab,
) {
  const include = DETAIL_INCLUDE_BY_TAB[tab];
  return useQuery({
    queryKey: ["orders", "detail", orderId, include],
    queryFn: () => fetchOrderDetail(orderId!, { include }),
    enabled: orderId != null,
    staleTime: DETAIL_STALE_MS,
    placeholderData: (prev) => prev,
  });
}

export function useCustomersQuery(page: number, search: string) {
  const offset = (page - 1) * 20;
  return useQuery({
    queryKey: ["customers", "list", page, search],
    queryFn: () =>
      listCustomers({
        limit: 20,
        offset,
        q: search.trim() || undefined,
      }),
    staleTime: 30_000,
    refetchInterval: pollWhenVisible(POLL_MS),
    placeholderData: (prev) => prev,
  });
}

export function useRidersQuery() {
  return useQuery({
    queryKey: ["riders", "list"],
    queryFn: fetchRiders,
    staleTime: POLL_MS,
    refetchInterval: pollWhenVisible(POLL_MS),
    placeholderData: (prev) => prev,
  });
}

export function useConversationsQuery() {
  return useQuery({
    queryKey: ["conversations", "list"],
    queryFn: fetchConversations,
    staleTime: POLL_MS,
    refetchInterval: pollWhenVisible(POLL_MS),
    placeholderData: (prev) => prev,
  });
}

export function useConversationMessagesQuery(conversationId: number | null) {
  return useQuery({
    queryKey: ["conversations", "messages", conversationId],
    queryFn: () => fetchMessages(conversationId!),
    enabled: conversationId != null,
    staleTime: POLL_MS,
    refetchInterval: pollWhenVisible(POLL_MS),
    placeholderData: (prev) => prev,
  });
}

export function useTicketsQuery(phoneFilter: string) {
  return useQuery({
    queryKey: ["tickets", "list", phoneFilter],
    queryFn: () => listTickets(undefined, phoneFilter.trim() || undefined),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}

export function useCustomerProfileQuery(customerId: number | null) {
  return useQuery({
    queryKey: ["customers", "profile", customerId],
    queryFn: () => getCustomerProfile(customerId!),
    enabled: customerId != null,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}

export function useCustomerWalletQuery(customerId: number | null) {
  return useQuery({
    queryKey: ["customers", "wallet", customerId],
    queryFn: async () => {
      const [balance, entries] = await Promise.all([
        getWallet(customerId!),
        getWalletEntries(customerId!),
      ]);
      return { balance, entries };
    },
    enabled: customerId != null,
    staleTime: 30_000,
    retry: false,
  });
}

export function useCustomerCouponsQuery(phone: string | null | undefined) {
  return useQuery({
    queryKey: ["customers", "coupons", phone],
    queryFn: () => listCoupons(phone!),
    enabled: !!phone,
    staleTime: 30_000,
    retry: false,
  });
}

export function useOpenTicketsCountQuery(enabled = true) {
  return useQuery({
    queryKey: ["tickets", "open-count"],
    queryFn: async () => {
      const rows = await listTickets("open");
      return rows.length;
    },
    // Tickets is manager/staff-only; roles without access (cashier, waiter,
    // kitchen, rider) must NOT fire this — a 401 here would trip the global
    // auth interceptor and bounce a valid staff session back to /login.
    enabled,
    staleTime: 30_000,
    refetchInterval: pollWhenVisible(30_000),
    retry: false,
  });
}