import type { PrinterPort } from "./native/printer";

interface PendingPrintJob {
  id: number;
  station_id: number;
  order_id: number;
  payload: string;
  status: string;
}

async function reportStatus(
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
  jobId: number,
  newStatus: "sent" | "failed",
): Promise<void> {
  await fetchImpl(new URL(`/api/v1/kds/print-jobs/${jobId}/status?new_status=${newStatus}`, apiBase).toString(), {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function pollAndPrint(
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
  printer: PrinterPort,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetchImpl(new URL("/api/v1/kds/print-jobs/pending", apiBase).toString(), {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    return; // offline — retried next tick
  }
  if (!resp.ok) return;

  const jobs = (await resp.json()) as PendingPrintJob[];
  for (const job of jobs) {
    try {
      await printer.print({ stationId: job.station_id, payload: job.payload });
      await reportStatus(apiBase, fetchImpl, token, job.id, "sent");
    } catch {
      await reportStatus(apiBase, fetchImpl, token, job.id, "failed");
    }
  }
}
