import { apiClient } from "./apiClient";
import type { CatalogSyncResult } from "./catalogApi";

export interface UnifiedMenuItem {
  link_status: "linked" | "dish_only" | "catalog_only";
  dish_id: number | null;
  catalog_product_id: number | null;
  retailer_id: string | null;
  dish_number: number | null;
  name: string;
  price_aed: number | null;
  category: string | null;
  description: string | null;
  is_available: boolean;
  catalog_active: boolean | null;
  image_url: string | null;
  /** Live on WhatsApp (Meta finished processing the image) vs still in review. */
  sendable: boolean | null;
  review_status: string | null;
}

export interface UnifiedMenu {
  menu_id: number | null;
  catalog_id: string;
  items: UnifiedMenuItem[];
  linked_count: number;
  dish_only_count: number;
  catalog_only_count: number;
}

export async function fetchUnifiedMenu(): Promise<UnifiedMenu> {
  return apiClient.get<UnifiedMenu>("/api/v1/menu/unified");
}

export async function syncCatalogFull(): Promise<CatalogSyncResult> {
  return apiClient.post<CatalogSyncResult>("/api/v1/catalog/sync-full", {});
}