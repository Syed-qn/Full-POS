import { describe, it, expect, vi } from "vitest";
import { pollAndPrint } from "./printJobPoller";
import type { PrinterPort } from "./native/printer";

describe("pollAndPrint", () => {
  it("fetches pending jobs, prints each, and reports success back to the API", async () => {
    const pending = [
      { id: 1, station_id: 5, order_id: 100, payload: "Order T-0001\n2x Kebab", status: "pending" },
    ];
    const fakeFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => pending })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    const printer: PrinterPort = { print: vi.fn().mockResolvedValue(undefined) };

    await pollAndPrint("http://api.test", fakeFetch as unknown as typeof fetch, "tok", printer);

    expect(printer.print).toHaveBeenCalledWith({ stationId: 5, payload: "Order T-0001\n2x Kebab" });
    expect(fakeFetch).toHaveBeenNthCalledWith(
      1,
      "http://api.test/api/v1/kds/print-jobs/pending",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer tok" }) }),
    );
    expect(fakeFetch).toHaveBeenNthCalledWith(
      2,
      "http://api.test/api/v1/kds/print-jobs/1/status?new_status=sent",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("reports failed status when the printer throws, and does not stop the batch", async () => {
    const pending = [
      { id: 1, station_id: 5, order_id: 100, payload: "job A", status: "pending" },
      { id: 2, station_id: 5, order_id: 101, payload: "job B", status: "pending" },
    ];
    const fakeFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => pending })
      .mockResolvedValue({ ok: true, json: async () => ({}) });

    const printer: PrinterPort = {
      print: vi.fn().mockRejectedValueOnce(new Error("printer offline")).mockResolvedValueOnce(undefined),
    };

    await pollAndPrint("http://api.test", fakeFetch as unknown as typeof fetch, "tok", printer);

    expect(printer.print).toHaveBeenCalledTimes(2);
    expect(fakeFetch).toHaveBeenNthCalledWith(
      2,
      "http://api.test/api/v1/kds/print-jobs/1/status?new_status=failed",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(fakeFetch).toHaveBeenNthCalledWith(
      3,
      "http://api.test/api/v1/kds/print-jobs/2/status?new_status=sent",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("does nothing when offline (fetch rejects)", async () => {
    const fakeFetch = vi.fn().mockRejectedValue(new Error("network down"));
    const printer: PrinterPort = { print: vi.fn() };

    await expect(
      pollAndPrint("http://api.test", fakeFetch as unknown as typeof fetch, "tok", printer),
    ).resolves.toBeUndefined();
    expect(printer.print).not.toHaveBeenCalled();
  });
});
