import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RiderAppScreen } from "./RiderAppScreen";

describe("RiderAppScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders pairing screen by default", () => {
    render(
      <MemoryRouter>
        <RiderAppScreen />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Rider App" })).toBeInTheDocument();
    expect(screen.getByLabelText("Pairing code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pair device" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use demo task list" })).toBeInTheDocument();
  });

  it("loads demo task list with COD and sticky primary action", async () => {
    render(
      <MemoryRouter>
        <RiderAppScreen />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Use demo task list" }));

    expect(await screen.findByText("Deliveries")).toBeInTheDocument();
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
    expect(screen.getByTestId("cod-strip")).toHaveTextContent("AED");
    expect(screen.getByTestId("pickup-card")).toBeInTheDocument();
    expect(screen.getByTestId("primary-action")).toHaveTextContent("Picked Up");

    fireEvent.click(screen.getByTestId("primary-action"));
    await waitFor(() =>
      expect(screen.getByTestId("primary-action")).toHaveTextContent("Arriving"),
    );
    expect(screen.getByTestId("active-stop")).toBeInTheDocument();
    expect(screen.getByTestId("cod-101")).toHaveTextContent("48.50");
  });

  it("requires failure reason for undeliverable", async () => {
    render(
      <MemoryRouter>
        <RiderAppScreen />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Use demo task list" }));
    fireEvent.click(await screen.findByTestId("primary-action")); // Picked Up
    await waitFor(() =>
      expect(screen.getByTestId("primary-action")).toHaveTextContent("Arriving"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(screen.getByTestId("fail-panel")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Customer unreachable" }));
    await waitFor(() =>
      expect(screen.queryByTestId("cod-101")).not.toBeInTheDocument(),
    );
  });
});
