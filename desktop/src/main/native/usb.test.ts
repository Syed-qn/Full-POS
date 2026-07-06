import { describe, it, expect } from "vitest";
import { NotImplementedUsb } from "./usb";

describe("NotImplementedUsb", () => {
  it("rejects listDevices() until a later phase implements it", async () => {
    const usb = new NotImplementedUsb();
    await expect(usb.listDevices()).rejects.toThrow(
      "usb not implemented — see hardware SDK phase",
    );
  });
});
