import { apiClient } from "./apiClient";

export interface CatalogProductOut {
  id: number;
  retailer_id: string;
  name: string;
  price_aed: number | null;
  currency: string | null;
  availability: string | null;
  image_url: string | null;
  category: string | null;
  is_active: boolean;
  synced_at: string | null;
}

export interface CatalogSyncResult {
  added: number;
  updated: number;
  deactivated: number;
  total_active: number;
  linked?: number;
  created?: number;
  pushed?: number;
  push_updated?: number;
  push_errors?: string[];
  products: CatalogProductOut[];
}

/** Products mirrored from the Meta catalogue (OPS view). */
export async function fetchCatalogProducts(): Promise<CatalogProductOut[]> {
  return apiClient.get<CatalogProductOut[]>("/api/v1/catalog/products");
}

/** Pull the latest products from Meta into the local mirror. */
export async function syncCatalog(): Promise<CatalogSyncResult> {
  return apiClient.post<CatalogSyncResult>("/api/v1/catalog/sync", {});
}

/**
 * Bulk push: send every available, priced dish to Meta Commerce Manager
 * (create-or-update + link to WhatsApp), then re-pull the mirror. Same push
 * path (push_dishes_to_meta) that a single add/edit triggers automatically.
 */
export async function pushCatalog(): Promise<CatalogSyncResult> {
  return apiClient.post<CatalogSyncResult>("/api/v1/catalog/push", {});
}
