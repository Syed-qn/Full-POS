import { apiClient } from "./apiClient";
import type { Coupon, CouponCreateIn } from "./types";

export async function listCoupons(): Promise<Coupon[]> {
  return apiClient.get<Coupon[]>("/api/v1/coupons");
}

export async function createCoupon(body: CouponCreateIn): Promise<Coupon> {
  return apiClient.post<Coupon>("/api/v1/coupons", body);
}

export async function pauseCoupon(code: string): Promise<Coupon> {
  return apiClient.post<Coupon>(`/api/v1/coupons/${encodeURIComponent(code)}/pause`, {});
}

export async function issueCouponToCustomer(
  customerId: number,
  discountAed: string,
): Promise<Coupon> {
  return apiClient.post<Coupon>("/api/v1/coupons/issue", {
    customer_id: customerId,
    discount_aed: discountAed,
  });
}
