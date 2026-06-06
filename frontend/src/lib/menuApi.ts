import { apiClient } from "./apiClient";
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
