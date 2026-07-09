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
    expect(screen.getByText(/E-invoicing readiness/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/PINT-AE-JSON-v1/)).toBeInTheDocument();
    });
  });
});
