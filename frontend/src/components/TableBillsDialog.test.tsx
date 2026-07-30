import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TableBillsDialog } from "./TableBillsDialog";
import type { TableBill } from "../lib/floorApi";

function bill(over: Partial<TableBill> = {}): TableBill {
  return {
    order_id: 1,
    order_number: "R1-0006",
    daily_token: 6,
    total_aed: "26.00",
    guest_label: null,
    ...over,
  };
}

describe("TableBillsDialog", () => {
  it("numbers unlabelled bills by position, first party first", async () => {
    // The bug this pins: the label used to be STAMPED on the order at create
    // time from a stale bill count, so a table with two bills showed "Bill 2"
    // twice — and a stored number stays wrong once Bill 1 is paid. The number is
    // now derived from this list, which the server sends oldest-first.
    render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[
          bill({ order_id: 6, order_number: "R1-0006", daily_token: 6, total_aed: "26.00" }),
          bill({ order_id: 7, order_number: "R1-0007", daily_token: 7, total_aed: "14.00" }),
        ]}
        onPick={() => {}}
        onClose={() => {}}
      />,
    );

    const rows = await screen.findAllByRole("button", { name: /^Bill \d/ });
    expect(rows).toHaveLength(2);
    // Bill 1 is the OLDER bill (R1-0006), not the newest.
    expect(rows[0]).toHaveTextContent("Bill 1");
    expect(rows[0]).toHaveTextContent("R1-0006");
    expect(rows[1]).toHaveTextContent("Bill 2");
    expect(rows[1]).toHaveTextContent("R1-0007");
    // Never the same label twice — that was the whole complaint.
    expect(screen.queryAllByText("Bill 2")).toHaveLength(1);
  });

  it("scales past two bills", async () => {
    render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[
          bill({ order_id: 1 }),
          bill({ order_id: 2 }),
          bill({ order_id: 3 }),
          bill({ order_id: 4 }),
        ]}
        onPick={() => {}}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText("Bill 4")).toBeInTheDocument();
    expect(screen.getByText(/4 bills/)).toBeInTheDocument();
  });

  it("ignores a stored label that is really a machine-guessed position", async () => {
    // Rows an earlier build stamped are still in the database, and they duplicate:
    // one table came back "Bill 3 · Bill 2 · Bill 3". Those are not human names, so
    // the position wins over them rather than the labels being data-migrated.
    render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[
          bill({ order_id: 5, guest_label: "Bill 3" }),
          bill({ order_id: 6, guest_label: "Bill 2" }),
          bill({ order_id: 7, guest_label: "Bill 3" }),
        ]}
        onPick={() => {}}
        onClose={() => {}}
      />,
    );

    const rows = await screen.findAllByRole("button", { name: /^Bill \d/ });
    expect(rows.map((r) => r.textContent?.match(/Bill \d/)?.[0])).toEqual([
      "Bill 1",
      "Bill 2",
      "Bill 3",
    ]);
  });

  it("prefers a name a human gave the bill over the position", async () => {
    render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[bill({ order_id: 6, guest_label: "Ahmed" }), bill({ order_id: 7 })]}
        onPick={() => {}}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByText("Ahmed")).toBeInTheDocument();
    // The unnamed one still reads by position, and keeps its own index.
    expect(screen.getByText("Bill 2")).toBeInTheDocument();
  });

  it("hands back the bill that was tapped", async () => {
    const onPick = vi.fn();
    render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[bill({ order_id: 6 }), bill({ order_id: 7 })]}
        onPick={onPick}
        onClose={() => {}}
      />,
    );
    await userEvent.click(await screen.findByTestId("table-bill-7"));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ order_id: 7 }));
  });

  it("offers Split bill only when the caller supports it", async () => {
    const { unmount } = render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[bill()]}
        onPick={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByTestId("table-bills-split")).not.toBeInTheDocument();
    unmount();

    const onSplit = vi.fn();
    render(
      <TableBillsDialog
        tableLabel="A01"
        bills={[bill()]}
        onPick={() => {}}
        onSplit={onSplit}
        onClose={() => {}}
      />,
    );
    await userEvent.click(await screen.findByTestId("table-bills-split"));
    expect(onSplit).toHaveBeenCalled();
  });
});
