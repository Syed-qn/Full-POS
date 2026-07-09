import { ApiError, apiClient } from "./apiClient";
import type { DishOut, MenuOut, MenuWithDiffOut, PriceRuleOut } from "./types";

export async function getMenu(menuId: number): Promise<MenuOut> {
  return apiClient.get<MenuOut>(`/api/v1/menus/${menuId}`);
}

/** Get the active menu, creating an empty one if the restaurant has none — lets
 *  "+ Add dish" work before any menu upload. */
export async function createBlankMenu(): Promise<MenuOut> {
  return apiClient.post<MenuOut>("/api/v1/menus/blank");
}

export async function uploadMenu(files: File[]): Promise<MenuWithDiffOut> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return apiClient.postForm<MenuWithDiffOut>("/api/v1/menus", form);
}

export async function activateMenu(menuId: number): Promise<MenuOut> {
  return apiClient.post<MenuOut>(`/api/v1/menus/${menuId}/activate`);
}

export async function setAvailability(dishId: number, isAvailable: boolean): Promise<DishOut> {
  return apiClient.patch<DishOut>(`/api/v1/dishes/${dishId}/availability`, {
    is_available: isAvailable,
  });
}

/** Turn a dish's WhatsApp catalogue presence on/off. Off → unpublished from Meta and
 *  hidden from WhatsApp; on → republished (shows once Meta finishes processing it). */
export async function setWhatsapp(dishId: number, enabled: boolean): Promise<DishOut> {
  return apiClient.patch<DishOut>(`/api/v1/dishes/${dishId}/whatsapp`, { enabled });
}

export interface VariantInput {
  name: string;
  price_aed: string;
  dish_number?: number | null;
}

export interface DishInput {
  dish_number: number;
  name: string;
  price_aed: string;
  category?: string | null;
  description?: string | null;
  // Meta Commerce catalogue product fields.
  image_url?: string | null;
  sale_price_aed?: string | null;
  fb_product_category?: string | null;
  condition?: string;
  meta_status?: string;
  brand?: string | null;
  catalog_retailer_id?: string | null;
  variants?: VariantInput[];
  allergens?: string[];
  name_ar?: string | null;
  description_ar?: string | null;
  nutrition?: Record<string, number | string>;
  channels_allowed?: string[];
  brand_menu_code?: string | null;
  stock_remaining?: number | null;
  auto_hide_when_oos?: boolean;
  available_from?: string | null;
  available_until?: string | null;
}

export type DishPatchInput = Partial<DishInput>;

/** Upload a dish photo (JPG/PNG, ≤5 MB) and get back its public URL to store on the
 *  dish. Meta fetches this URL as the catalogue product image. */
export async function uploadDishImage(file: File): Promise<{ url: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiClient.postForm<{ url: string }>("/api/v1/dishes/image", form);
}

export async function addDish(menuId: number, body: DishInput): Promise<DishOut> {
  return apiClient.post<DishOut>(`/api/v1/menus/${menuId}/dishes`, body);
}

export async function patchDish(
  menuId: number,
  dishId: number,
  body: DishPatchInput,
): Promise<DishOut> {
  return apiClient.patch<DishOut>(`/api/v1/menus/${menuId}/dishes/${dishId}`, body);
}

export async function submitMenuForApproval(menuId: number): Promise<MenuOut> {
  return apiClient.post<MenuOut>(`/api/v1/menus/${menuId}/submit-for-approval`);
}

export async function approveMenu(menuId: number): Promise<MenuOut> {
  return apiClient.post<MenuOut>(`/api/v1/menus/${menuId}/approve`);
}

export async function bulkPriceUpdate(
  menuId: number,
  body: { dish_ids: number[]; price_aed?: string; percent_delta?: string },
): Promise<{ updated: number; dish_ids: number[] }> {
  return apiClient.post(`/api/v1/menus/${menuId}/bulk-price-update`, body);
}

export async function bulkCsvImport(
  menuId: number,
  file: File,
): Promise<{ created: number; updated: number; errors: string[] }> {
  const form = new FormData();
  form.append("file", file);
  return apiClient.postForm(`/api/v1/menus/${menuId}/bulk-csv-import`, form);
}

export async function createCategory(body: {
  name: string;
  sort_order?: number;
  parent_id?: number | null;
}): Promise<{ id: number; name: string; sort_order: number; parent_id: number | null }> {
  return apiClient.post("/api/v1/categories", body);
}

export async function listCategories(): Promise<
  Array<{ id: number; name: string; sort_order: number; parent_id: number | null }>
> {
  return apiClient.get("/api/v1/categories");
}

export async function createSellRule(body: {
  rule_kind: "upsell" | "cross_sell";
  suggest_dish_id: number;
  trigger_dish_id?: number | null;
  trigger_category?: string | null;
  message?: string | null;
}): Promise<unknown> {
  return apiClient.post("/api/v1/menus/sell-rules", body);
}

export async function deleteDish(menuId: number, dishId: number): Promise<void> {
  await apiClient.delete<void>(`/api/v1/menus/${menuId}/dishes/${dishId}`);
}

export async function fetchActiveMenu(): Promise<MenuOut | null> {
  try {
    return await apiClient.get<MenuOut>("/api/v1/menus/active");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

// ── Dish price rules (time/channel/branch overrides) ─────────────────────────

export interface PriceRuleInput {
  rule_type: string;
  price_aed: string;
  channel?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  days_of_week?: number[] | null;
}

export async function listPriceRules(dishId: number): Promise<PriceRuleOut[]> {
  return apiClient.get<PriceRuleOut[]>(`/api/v1/dishes/${dishId}/price-rules`);
}

export async function createPriceRule(
  dishId: number,
  body: PriceRuleInput,
): Promise<PriceRuleOut> {
  return apiClient.post<PriceRuleOut>(`/api/v1/dishes/${dishId}/price-rules`, body);
}

export async function deletePriceRule(dishId: number, ruleId: number): Promise<void> {
  await apiClient.delete<void>(`/api/v1/dishes/${dishId}/price-rules/${ruleId}`);
}
