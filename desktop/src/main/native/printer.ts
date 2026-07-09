import fs from "fs";
import path from "path";

export interface PrintJob {
  stationId: number;
  payload: string;
  kind?: "kot" | "receipt";
}

export interface PrinterPort {
  print(job: PrintJob): Promise<void>;
}

/** Stub used when no hardware is attached — rejects so poller can failover. */
export class NotImplementedPrinter implements PrinterPort {
  async print(_job: PrintJob): Promise<void> {
    throw new Error("printer not implemented — see Phase B spec");
  }
}

/**
 * File-backed printer for offline/dev: writes KOT/receipt tickets under a spool dir.
 * Enables offline KOT + receipt printing without physical hardware.
 */
export class FileSpoolPrinter implements PrinterPort {
  constructor(private spoolDir: string) {
    fs.mkdirSync(spoolDir, { recursive: true });
  }

  async print(job: PrintJob): Promise<void> {
    const kind = job.kind ?? "kot";
    const name = `${kind}_${job.stationId}_${Date.now()}.txt`;
    const file = path.join(this.spoolDir, name);
    fs.writeFileSync(file, job.payload, "utf8");
  }
}

/** Tries primary printer, then failover printer (device failover path). */
export class FailoverPrinter implements PrinterPort {
  constructor(
    private primary: PrinterPort,
    private fallback: PrinterPort,
  ) {}

  async print(job: PrintJob): Promise<void> {
    try {
      await this.primary.print(job);
    } catch {
      await this.fallback.print(job);
    }
  }
}
