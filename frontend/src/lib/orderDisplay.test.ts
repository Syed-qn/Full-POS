import { describe, expect, it } from "vitest";
import { isResaleCopy, orderStatusLabel } from "./orderDisplay";

describe("orderDisplay", () => {
  it("labels resale parent vs copy", () => {
    expect(orderStatusLabel("on_resale", { orderNumber: "R1-0077" })).toBe(
      "Cancelled (resale)",
    );
    expect(
      orderStatusLabel("on_resale", {
        orderNumber: "R1-0077-RS",
        resaleOfOrderId: 89,
      }),
    ).toBe("Resale offer");
  });

  it("detects resale copies", () => {
    expect(isResaleCopy({ order_number: "R1-0077-RS", resale_of_order_id: 1 })).toBe(
      true,
    );
    expect(isResaleCopy({ order_number: "R1-0077" })).toBe(false);
  });
});