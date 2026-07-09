import { describe, it, expect, afterEach } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";
import { FailoverPrinter, FileSpoolPrinter, NotImplementedPrinter } from "./printer";

const tmpDirs: string[] = [];
afterEach(() => {
  for (const d of tmpDirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

describe("Printers", () => {
  it("NotImplementedPrinter rejects print()", async () => {
    const printer = new NotImplementedPrinter();
    await expect(printer.print({ stationId: 1, payload: "test ticket" })).rejects.toThrow(
      "printer not implemented — see Phase B spec",
    );
  });

  it("FileSpoolPrinter writes KOT/receipt offline", async () => {
    const dir = path.join(os.tmpdir(), `spool-test-${Date.now()}`);
    tmpDirs.push(dir);
    const printer = new FileSpoolPrinter(dir);
    await printer.print({ stationId: 2, payload: "KOT line", kind: "kot" });
    await printer.print({ stationId: 0, payload: "RECEIPT", kind: "receipt" });
    expect(fs.readdirSync(dir).length).toBe(2);
  });

  it("FailoverPrinter falls back when primary fails", async () => {
    const dir = path.join(os.tmpdir(), `spool-fb-${Date.now()}`);
    tmpDirs.push(dir);
    const printer = new FailoverPrinter(new NotImplementedPrinter(), new FileSpoolPrinter(dir));
    await printer.print({ stationId: 1, payload: "via failover" });
    expect(fs.readdirSync(dir).length).toBe(1);
  });
});
