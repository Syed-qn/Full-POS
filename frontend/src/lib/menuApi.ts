import { ApiError, apiClient } from "./apiClient";
import type { DishOut, MenuOut, MenuWithDiffOut } from "./types";

export async function getMenu(menuId: number): Promise<MenuOut> {
  return apiClient.get<MenuOut>(`/api/v1/menus/${menuId}`);
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
  variants?: VariantInput[];
}

export type DishPatchInput = Partial<DishInput>;

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
