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
