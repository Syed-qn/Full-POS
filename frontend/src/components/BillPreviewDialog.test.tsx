import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BillPreviewDialog } from "./BillPreviewDialog";
import type { TaxConfig } from "../lib/useTaxConfig";

const TAX_20_EXCLUSIVE: TaxConfig = {
  rate: 0.2,
  percent: 20,
  mode: "exclusive",
  ready: true,
};

function renderSlip(over: Partial<Parameters<typeof BillPreviewDialog>[0]> = {}) {
  return render(
    <BillPreviewDialog
      lines={[{ name: "Plater Meal", qty: 1, unitPrice: 29, lineTotal: 29 }]}
      subtotal={29}
      deliveryFee={0}
      adjustments={-9}
      total={20}
      taxCfg={TAX_20_EXCLUSIVE}
      restaurantName="LA CAFE"
      orderTypeLabel="Take Away"
      tokenNumber={13}
      billNumber="R1-0034"
      tableLabel={null}
      waiterName="Allen (Cashier)"
      customerName="Take away"
      onClose={vi.fn()}
      {...over}
    />,
  );
}

describe("BillPreviewDialog totals", () => {
  it("the slip adds up", () => {
    // The real bill that was wrong: 29.00 − 9.00 = 20.00, but a "VAT 4.00 on
    // top" line printed above a total of 20.00. A guest checks this arithmetic.
    renderSlip();
    expect(screen.getByTestId("bill-preview-adjustments")).toHaveTextContent("-9.00");
    expect(screen.getByTestId("bill-preview-total")).toHaveTextContent("20.00");
    // 20.00 gross at 20% contains 3.33, not 4.00 — and it is stated as contained.
    expect(screen.getByTestId("bill-preview-vat")).toHaveTextContent("3.33");
    expect(screen.getByTestId("bill-preview-slip")).toHaveTextContent(/of which VAT \(20% incl\.\)/);
    expect(screen.getByTestId("bill-preview-slip")).not.toHaveTextContent(/on top/);
  });

  it("takes VAT after the discount, on what was actually paid", () => {
    renderSlip({ adjustments: 0, subtotal: 29, total: 29 });
    // 29.00 / 1.2 = 24.1667 net → 4.83 tax.
    expect(screen.getByTestId("bill-preview-vat")).toHaveTextContent("4.83");
  });

  it("prints no tax line until the server has confirmed a rate", () => {
    // A wrong tax figure on a bill is worse than none at all.
    renderSlip({ taxCfg: { rate: 0, percent: 0, mode: "inclusive", ready: false } });
    expect(screen.queryByTestId("bill-preview-vat")).not.toBeInTheDocument();
  });

  it("shows a charge, not a discount, when the total exceeds the lines", () => {
    renderSlip({ adjustments: 3.5, total: 32.5 });
    expect(screen.getByTestId("bill-preview-adjustments")).toHaveTextContent("3.50");
    expect(screen.getByTestId("bill-preview-slip")).toHaveTextContent(/Charges/);
  });
});
