import { describe, it, expect } from "vitest";
import { NotImplementedPrinter } from "./printer";

describe("NotImplementedPrinter", () => {
  it("rejects print() until Phase B implements a real driver", async () => {
    const printer = new NotImplementedPrinter();
    await expect(printer.print({ stationId: 1, payload: "test ticket" })).rejects.toThrow(
      "printer not implemented — see Phase B spec",
    );
  });
});
