import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePoll } from "./usePoll";

function Probe({ fetcher }: { fetcher: () => Promise<string> }) {
  const { data, error } = usePoll(fetcher, 1000);
  return <div>{error ? `err:${String(error)}` : (data ?? "loading")}</div>;
}

describe("usePoll", () => {
  it("renders fetched data", async () => {
    const fetcher = vi.fn(async () => "HELLO");
    render(<Probe fetcher={fetcher} />);
    await waitFor(() => expect(screen.getByText("HELLO")).toBeInTheDocument());
  });
});
