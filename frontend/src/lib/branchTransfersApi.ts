/** Branch-to-branch stock transfers, from a branch's point of view.
 *
 * Separate from organizationsApi on purpose: that module signs its calls with
 * the HQ org token, and these endpoints take the ordinary restaurant session —
 * owner login or a manager PIN. The branch is read from the token server-side,
 * so nothing here sends a "from" id: you can only ever send from where you are.
 */
import { apiClient } from "./apiClient";
import type {
  BranchTransferDispatchIn,
  BranchTransferOut,
  BranchTransferRequestIn,
  SiblingBranchOut,
} from "./types";

type TransferResult = Promise<{ id: number; status: string }>;

/** Branches you may send to. Empty for a single-site restaurant — the caller
 *  uses that to keep the Transfers tab off screen entirely. */
export function listSiblingBranches(): Promise<SiblingBranchOut[]> {
  return apiClient.get<SiblingBranchOut[]>("/api/v1/branch-transfers/branches");
}

export function listBranchTransfers(): Promise<BranchTransferOut[]> {
  return apiClient.get<BranchTransferOut[]>("/api/v1/branch-transfers");
}

/** Send stock out. Deducts here immediately — once the van has gone the food
 *  is not in this kitchen. */
export function dispatchBranchTransfer(
  body: BranchTransferDispatchIn,
): Promise<{ id: number; status: string }> {
  return apiClient.post<{ id: number; status: string }>("/api/v1/branch-transfers", body);
}

/** Ask another branch to send you stock. Moves nothing until they agree. */
export function requestBranchStock(body: BranchTransferRequestIn): TransferResult {
  return apiClient.post("/api/v1/branch-transfers/requests", body);
}

/** Agree to a request and send it. Pass lines only to send LESS than was
 *  asked for — the request stays on the record either way. */
export function approveBranchRequest(
  transferId: number,
  lines: Array<{ ingredient_name: string; quantity: string }> = [],
): TransferResult {
  return apiClient.post(`/api/v1/branch-transfers/${transferId}/approve`, { lines });
}

/** Turn a request down. Nothing has moved, so nothing is returned. */
export function declineBranchRequest(
  transferId: number,
  reason?: string,
): TransferResult {
  return apiClient.post(`/api/v1/branch-transfers/${transferId}/decline`, {
    reason: reason || null,
  });
}

/** Take back a request you raised, before the other branch acts on it. */
export function withdrawBranchRequest(transferId: number): TransferResult {
  return apiClient.post(`/api/v1/branch-transfers/${transferId}/withdraw`, {});
}

/** Confirm arrival. Pass nothing when everything came as sent, which is the
 *  ordinary case; pass lines to record a short delivery. */
export function receiveBranchTransfer(
  transferId: number,
  lines: Array<{ ingredient_name: string; qty_received: string }> = [],
): Promise<{ id: number; status: string }> {
  return apiClient.post<{ id: number; status: string }>(
    `/api/v1/branch-transfers/${transferId}/receive`,
    { lines },
  );
}

/** Call the van back. Sender only, and only before the other branch accepts. */
export function cancelBranchTransfer(
  transferId: number,
): Promise<{ id: number; status: string }> {
  return apiClient.post<{ id: number; status: string }>(
    `/api/v1/branch-transfers/${transferId}/cancel`,
    {},
  );
}
