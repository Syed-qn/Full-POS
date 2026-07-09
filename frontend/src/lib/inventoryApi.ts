import { apiClient } from "./apiClient";
import type {
  BatchIn,
  BatchOut,
  CostIn,
  IngredientIn,
  IngredientOut,
  InventoryValuationOut,
  LowStockAlertOut,
  PurchaseOrderIn,
  PurchaseOrderOut,
  RecipeLinkIn,
  ReorderSuggestionOut,
  RestockIn,
  StockAdjustmentIn,
  StockAdjustmentOut,
  StockAdjustmentStatus,
  StockClosingOut,
  StockCountIn,
  StockCountOut,
  SubstituteIn,
  SubstituteOut,
  VendorIn,
  VendorOut,
  VendorPriceComparisonOut,
  WasteIn,
} from "./types";

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, value);
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export function listIngredients(): Promise<IngredientOut[]> {
  return apiClient.get<IngredientOut[]>("/api/v1/ingredients");
}

export function createIngredient(body: IngredientIn): Promise<IngredientOut> {
  return apiClient.post<IngredientOut>("/api/v1/ingredients", body);
}

export function restockIngredient(ingredientId: number, body: RestockIn): Promise<IngredientOut> {
  return apiClient.post<IngredientOut>(`/api/v1/ingredients/${ingredientId}/restock`, body);
}

export function wasteIngredient(ingredientId: number, body: WasteIn): Promise<IngredientOut> {
  return apiClient.post<IngredientOut>(`/api/v1/ingredients/${ingredientId}/waste`, body);
}

export function recordStockCount(ingredientId: number, body: StockCountIn): Promise<StockCountOut> {
  return apiClient.post<StockCountOut>(`/api/v1/ingredients/${ingredientId}/stock-count`, body);
}

export function updateIngredientCost(ingredientId: number, body: CostIn): Promise<IngredientOut> {
  return apiClient.patch<IngredientOut>(`/api/v1/ingredients/${ingredientId}/cost`, body);
}

export function createRecipeLink(ingredientId: number, body: RecipeLinkIn): Promise<{ id: number; dish_id: number; ingredient_id: number }> {
  return apiClient.post<{ id: number; dish_id: number; ingredient_id: number }>(
    `/api/v1/ingredients/${ingredientId}/recipe-links`,
    body,
  );
}

export function createBatch(ingredientId: number, body: BatchIn): Promise<BatchOut> {
  return apiClient.post<BatchOut>(`/api/v1/ingredients/${ingredientId}/batches`, body);
}

export function listExpiringSoon(withinDays = 3): Promise<BatchOut[]> {
  return apiClient.get<BatchOut[]>(`/api/v1/ingredients/expiring-soon${query({ within_days: String(withinDays) })}`);
}

export function createSubstitute(ingredientId: number, body: SubstituteIn): Promise<SubstituteOut> {
  return apiClient.post<SubstituteOut>(`/api/v1/ingredients/${ingredientId}/substitutes`, body);
}

export function listSubstitutes(ingredientId: number): Promise<SubstituteOut[]> {
  return apiClient.get<SubstituteOut[]>(`/api/v1/ingredients/${ingredientId}/substitutes`);
}

export function listStockAdjustments(status?: StockAdjustmentStatus): Promise<StockAdjustmentOut[]> {
  return apiClient.get<StockAdjustmentOut[]>(`/api/v1/ingredients/stock-adjustments${query({ status })}`);
}

export function createStockAdjustment(ingredientId: number, body: StockAdjustmentIn): Promise<StockAdjustmentOut> {
  return apiClient.post<StockAdjustmentOut>(`/api/v1/ingredients/${ingredientId}/stock-adjustments`, body);
}

export function approveStockAdjustment(adjustmentId: number): Promise<StockAdjustmentOut> {
  return apiClient.post<StockAdjustmentOut>(`/api/v1/ingredients/stock-adjustments/${adjustmentId}/approve`);
}

export function rejectStockAdjustment(adjustmentId: number): Promise<StockAdjustmentOut> {
  return apiClient.post<StockAdjustmentOut>(`/api/v1/ingredients/stock-adjustments/${adjustmentId}/reject`);
}

export function getVendorPriceComparison(ingredientId: number): Promise<VendorPriceComparisonOut[]> {
  return apiClient.get<VendorPriceComparisonOut[]>(`/api/v1/ingredients/${ingredientId}/vendor-price-comparison`);
}

export function getInventoryValuation(): Promise<InventoryValuationOut> {
  return apiClient.get<InventoryValuationOut>("/api/v1/reports/inventory-valuation");
}

export function sendLowStockAlert(): Promise<LowStockAlertOut> {
  return apiClient.post<LowStockAlertOut>("/api/v1/ingredients/low-stock-alert");
}

export function listLowStock(): Promise<IngredientOut[]> {
  return apiClient.get<IngredientOut[]>("/api/v1/ingredients/low-stock");
}

export function getReorderSuggestions(): Promise<ReorderSuggestionOut[]> {
  return apiClient.get<ReorderSuggestionOut[]>("/api/v1/ingredients/reorder-suggestions");
}

export function getDailyStockClosing(targetDate: string): Promise<StockClosingOut[]> {
  return apiClient.get<StockClosingOut[]>(`/api/v1/reports/daily-stock-closing${query({ target_date: targetDate })}`);
}

export function createVendor(body: VendorIn): Promise<VendorOut> {
  return apiClient.post<VendorOut>("/api/v1/vendors", body);
}

export function createPurchaseOrder(body: PurchaseOrderIn): Promise<PurchaseOrderOut> {
  return apiClient.post<PurchaseOrderOut>("/api/v1/purchase-orders", body);
}

export function receivePurchaseOrder(purchaseOrderId: number): Promise<PurchaseOrderOut> {
  return apiClient.post<PurchaseOrderOut>(`/api/v1/purchase-orders/${purchaseOrderId}/receive`);
}
