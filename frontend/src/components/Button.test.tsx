import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";

describe("Button a11y", () => {
  it("announces disabled state via disabled and aria-disabled", () => {
    render(
      <Button disabled variant="primary">
        Save
      </Button>,
    );
    const btn = screen.getByRole("button", { name: /save/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-disabled", "true");
  });

  it("does not set aria-disabled when enabled", () => {
    render(<Button>Save</Button>);
    const btn = screen.getByRole("button", { name: /save/i });
    expect(btn).toBeEnabled();
    expect(btn).not.toHaveAttribute("aria-disabled");
  });
});
