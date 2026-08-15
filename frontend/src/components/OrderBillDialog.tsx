import { useEffect, useState } from "react";
import { apiClient } from "../lib/apiClient";
import { fetchOrderDetail } from "../lib/orderDetailApi";
import type { OrderDetailOut, RestaurantOut } from "../lib/types";
import { useTaxConfig } from "../lib/useTaxConfig";
import { BillPreviewDialog, type BillLine } from "./BillPreviewDialog";

/* The shop name is the same on every slip of a shift, so it is fetched once per
   session rather than on each preview. */
let shopName: string | null = null;
let shopNameInflight: Promise<string | null> | null = null;

function loadShopName(): Promise<string | null> {
  if (shopName != null) return Promise.resolve(shopName);
  if (!shopNameInflight) {
    shopNameInflight = apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((r) => {
        shopName = r.name ?? null;
        return shopName;
      })
      .catch(() => null)
      .finally(() => {
        shopNameInflight = null;
      });
  }
  return shopNameInflight;
}

const TYPE_LABELS: Record<string, string> = {
  dine_in: "Dining",
  takeaway: "Take Away",
  delivery: "Home Delivery",
  online: "Online",
};

/**
 * The bill for an order that already exists on the server.
 *
 * The till's own preview builds its slip from the cart, because there is no
 * saved order yet. Every other surface — the takeaway and delivery tills, the
 * waiter's open tab, checkout — is looking at a saved order, and for those the
 * server is the only honest source: it holds the discounts, service charges and
 * partial cancellations that the screen's own list row does not.
 */
export function OrderBillDialog({
  orderId,
  onClose,
}: {
  orderId: number;
  onClose: () => void;
}) {
  const taxCfg = useTaxConfig();
  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [name, setName] = useState<string | null>(shopName);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    fetchOrderDetail(orderId, { include: "overview" })
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load the bill");
      });
    void loadShopName().then((n) => {
      if (!cancelled) setName(n);
    });
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (error) {
    return (
      <div
        role="alert"
        data-testid="order-bill-error"
        style={{ position: "fixed", inset: 0, zIndex: 1200 }}
        onClick={onClose}
      />
    );
  }
  if (!detail) return null;

  const lines: BillLine[] = detail.items.map((i) => {
    const unit = parseFloat(i.price_aed ?? "0") || 0;
    return {
      name: i.variant_name ? `${i.dish_name} (${i.variant_name})` : i.dish_name,
      qty: i.qty,
      unitPrice: unit,
      // line_total is the server's figure and can differ from unit × qty once a
      // line is discounted; it wins.
      lineTotal: parseFloat(i.line_total ?? "0") || unit * i.qty,
    };
  });

  const subtotal = parseFloat(detail.subtotal ?? "0") || 0;
  const deliveryFee = parseFloat(detail.delivery_fee_aed ?? "0") || 0;
  const total = parseFloat(detail.total ?? "0") || 0;
  // The server's total is what the customer is charged. Anything it does not
  // explain — a till discount, service or packaging — is printed as its own
  // line rather than quietly folded in, so the slip always reconciles.
  const adjustments = total - subtotal - deliveryFee;

  return (
    <BillPreviewDialog
      lines={lines}
      subtotal={subtotal}
      deliveryFee={deliveryFee}
      adjustments={adjustments}
      total={total}
      taxCfg={taxCfg}
      restaurantName={name}
      orderTypeLabel={TYPE_LABELS[detail.order_type ?? ""] ?? detail.order_type ?? "Bill"}
      tokenNumber={detail.daily_token ?? null}
      billNumber={detail.order_number}
      tableLabel={detail.table_label ?? null}
      waiterName={detail.staff_name ?? null}
      customerName={detail.customer?.name ?? null}
      onClose={onClose}
    />
  );
}
