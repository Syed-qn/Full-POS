import { apiClient } from "./apiClient";
import type {
  BatchIn,
  BatchOut,
  CostIn,
  GrnOut,
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
  StockAnomalyAlertOut,
  StockClosingOut,
  StockCountIn,
  StockCountOut,
  StockLocationOut,
  StockVarianceRow,
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

export function listVendors(activeOnly = true): Promise<VendorOut[]> {
  return apiClient.get<VendorOut[]>(
    `/api/v1/vendors${query({ active_only: activeOnly ? "true" : "false" })}`,
  );
}

export function createPurchaseOrder(body: PurchaseOrderIn): Promise<PurchaseOrderOut> {
  return apiClient.post<PurchaseOrderOut>("/api/v1/purchase-orders", body);
}

export function listPurchaseOrders(status?: string): Promise<PurchaseOrderOut[]> {
  return apiClient.get<PurchaseOrderOut[]>(
    `/api/v1/purchase-orders${query({ status })}`,
  );
}

export function receivePurchaseOrder(purchaseOrderId: number): Promise<PurchaseOrderOut> {
  return apiClient.post<PurchaseOrderOut>(`/api/v1/purchase-orders/${purchaseOrderId}/receive`);
}

export function createGrn(body: {
  po_id: number;
  lines: Array<{
    po_line_id: number;
    qty_received: string;
    unit_cost_aed?: string;
    expiry_date?: string | null;
  }>;
  notes?: string | null;
}): Promise<GrnOut> {
  return apiClient.post<GrnOut>("/api/v1/grn", body);
}

export function listGrns(poId?: number): Promise<GrnOut[]> {
  return apiClient.get<GrnOut[]>(
    `/api/v1/grn${query({ po_id: poId !== undefined ? String(poId) : undefined })}`,
  );
}

export function listStockLocations(): Promise<StockLocationOut[]> {
  return apiClient.get<StockLocationOut[]>("/api/v1/ingredients/locations");
}

export function createStockLocation(body: {
  name: string;
  code: string;
  kitchen_role?: string;
}): Promise<StockLocationOut> {
  return apiClient.post<StockLocationOut>("/api/v1/ingredients/locations", body);
}

export function getStockVarianceReport(startDate?: string, endDate?: string): Promise<StockVarianceRow[]> {
  return apiClient.get<StockVarianceRow[]>(
    `/api/v1/ingredients/reports/variance${query({
      start_date: startDate,
      end_date: endDate,
    })}`,
  );
}

export function getSpoilageReport(startDate: string, endDate: string): Promise<
  Array<{
    ingredient_id: number;
    ingredient_name: string;
    quantity: string;
    reason: string | null;
    reason_type: string;
    recorded_by: string;
    created_at: string | null;
  }>
> {
  return apiClient.get(
    `/api/v1/ingredients/reports/spoilage${query({
      start_date: startDate,
      end_date: endDate,
    })}`,
  );
}

export function getAnomalyAlerts(status = "open"): Promise<StockAnomalyAlertOut[]> {
  return apiClient.get<StockAnomalyAlertOut[]>(
    `/api/v1/ingredients/reports/anomaly-alerts${query({ status })}`,
  );
}

export function takeClosingSnapshot(targetDate?: string): Promise<
  Array<{
    ingredient_id: number;
    closing_stock: string;
    unit: string;
    valuation_aed?: string;
  }>
> {
  return apiClient.post(
    `/api/v1/ingredients/reports/closing-snapshot${query({
      target_date: targetDate,
    })}`,
  );
}
