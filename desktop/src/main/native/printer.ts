export interface PrintJob {
  stationId: number;
  payload: string;
}

export interface PrinterPort {
  print(job: PrintJob): Promise<void>;
}

export class NotImplementedPrinter implements PrinterPort {
  async print(_job: PrintJob): Promise<void> {
    throw new Error("printer not implemented — see Phase B spec");
  }
}
