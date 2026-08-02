import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ComplianceScreen } from "./ComplianceScreen";

vi.mock("../lib/complianceApi", () => ({
  getTaxSettings: vi.fn(),
  patchTaxSettings: vi.fn(),
  getEInvoiceReadiness: vi.fn(),
  listRefundNotes: vi.fn(),
  listEInvoiceTransmissions: vi.fn(),
  listRetentionRuns: vi.fn(),
  createRefundNote: vi.fn(),
  transmitEInvoice: vi.fn(),
  runRetention: vi.fn(),
  accountantExport: vi.fn(),
}));

import * as api from "../lib/complianceApi";

describe("ComplianceScreen", () => {
  beforeEach(() => {
    vi.mocked(api.getTaxSettings).mockResolvedValue({
      trn: "100123456700003",
      legal_name: "Test LLC",
      legal_name_ar: "اختبار",
      tax_pricing_mode: "exclusive",
      default_vat_rate: "0.0500",
      simplified_invoice_threshold_aed: "10000.00",
      data_retention_days: 2555,
      buyer_trn_required_for_b2b: true,
      e_invoice_enabled: false,
      asp_provider: "mock",
    });
    vi.mocked(api.getEInvoiceReadiness).mockResolvedValue({
      ready: true,
      e_invoice_enabled: false,
      asp_provider: "mock",
      asp_credentials_configured: true,
      structured_profile: "PINT-AE-JSON-v1",
      missing_fields: [],
      is_live: false,
      blockers: ["Switch e-invoicing on under Tax profile."],
      summary: "Not ready to send yet.",
      notes: "Mock ASP",
    });
    vi.mocked(api.listRefundNotes).mockResolvedValue([]);
    vi.mocked(api.listEInvoiceTransmissions).mockResolvedValue([]);
    vi.mocked(api.listRetentionRuns).mockResolvedValue([]);
  });

  it("renders UAE compliance dashboard", async () => {
    render(<ComplianceScreen />);
    await waitFor(() => {
      expect(screen.getByText("Compliance (UAE)")).toBeInTheDocument();
    });
    expect(screen.getByText("Save tax settings")).toBeInTheDocument();
    // E-invoice is hidden while the only ASP adapter is the mock, which files
    // nothing with the FTA but returns a reference that looks like it did.
    expect(screen.queryByRole("tab", { name: /e-invoice/i })).not.toBeInTheDocument();
    // Retention deletes error logs and abandoned carts, nothing fiscal. It is a
    // scheduled job wearing a compliance label, so it is not offered as a button.
    expect(screen.queryByRole("tab", { name: /Retention/ })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Refund notes/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Accountant export/ })).toBeInTheDocument();
  });

  it("shows a skeleton, not seeded defaults, while settings are still loading", async () => {
    // A restaurant on 20% used to read "5" sitting in the VAT box for as long as
    // the request took, because the inputs are seeded to be controlled.
    let release: (v: unknown) => void = () => {};
    vi.mocked(api.getTaxSettings).mockReturnValue(
      new Promise((r) => {
        release = r;
      }) as ReturnType<typeof api.getTaxSettings>,
    );

    render(<ComplianceScreen />);
    await waitFor(() => {
      expect(screen.getByLabelText("Loading tax settings")).toBeInTheDocument();
    });
    expect(screen.queryByDisplayValue("5")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("2555")).not.toBeInTheDocument();

    release({
      trn: null,
      legal_name: null,
      legal_name_ar: null,
      tax_pricing_mode: "inclusive",
      default_vat_rate: "0.2000",
      simplified_invoice_threshold_aed: "10000.00",
      data_retention_days: 2555,
      buyer_trn_required_for_b2b: true,
      e_invoice_enabled: false,
      asp_provider: "mock",
    });

    // The first rate the operator ever sees is the real one.
    await waitFor(() => {
      expect(screen.getByDisplayValue("20")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("Loading tax settings")).not.toBeInTheDocument();
  });

  it("hides the e-invoicing switch along with the tab it governs", async () => {
    render(<ComplianceScreen />);
    await waitFor(() => {
      expect(screen.getByDisplayValue("5")).toBeInTheDocument();
    });
    expect(screen.queryByText("E-invoicing enabled")).not.toBeInTheDocument();
  });
});
