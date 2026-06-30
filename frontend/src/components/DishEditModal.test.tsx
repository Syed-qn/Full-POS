import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DishEditModal } from "./DishEditModal";

// Toaster pulls in app-level context we don't need here.
vi.mock("./Toaster", () => ({ toast: vi.fn() }));

describe("DishEditModal serving-size variants", () => {
  afterEach(() => vi.restoreAllMocks());

  // A new dish must carry a photo before it can go live on WhatsApp — upload one so
  // the form is saveable. The image endpoint returns the stored URL.
  const pngFile = new File([new Uint8Array([1, 2, 3])], "dish.png", { type: "image/png" });
  async function uploadPhoto() {
    await userEvent.upload(screen.getByTestId("dish-image-input"), pngFile);
  }

  it("adds variant rows and submits them in the create body", async () => {
    let posted: any = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (typeof url === "string" && url.includes("/dishes/image")) {
          return Promise.resolve(
            new Response(JSON.stringify({ url: "https://cdn.test/media/dishes/1/p.png" }), {
              status: 201,
            }),
          );
        }
        if (init?.method === "POST") {
          posted = JSON.parse(init.body as string);
          return Promise.resolve(new Response(JSON.stringify({ id: 9 }), { status: 201 }));
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      }),
    );

    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );

    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Chicken Biryani");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "18.00");
    await uploadPhoto();

    await userEvent.click(screen.getByRole("button", { name: /add serving size/i }));
    await userEvent.type(screen.getByLabelText("Serving size 1 name"), "4 serve");
    await userEvent.type(screen.getByLabelText("Serving size 1 price"), "60");

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add dish" })).not.toBeDisabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add dish" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.variants).toEqual([{ name: "4 serve", price_aed: "60" }]);
    expect(posted.image_url).toBe("https://cdn.test/media/dishes/1/p.png");
  });

  it("requires a photo before a new dish can be added", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (typeof url === "string" && url.includes("/dishes/image")) {
          return Promise.resolve(
            new Response(JSON.stringify({ url: "https://cdn.test/media/dishes/1/p.png" }), {
              status: 201,
            }),
          );
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      }),
    );
    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Falooda");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "12.00");
    // Name + price filled but no photo yet → still blocked.
    expect(screen.getByRole("button", { name: "Add dish" })).toBeDisabled();
    await uploadPhoto();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add dish" })).not.toBeDisabled(),
    );
  });

  it("disables save while a variant row is partially filled", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 200 }))));
    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Biryani");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "18.00");
    await userEvent.click(screen.getByRole("button", { name: /add serving size/i }));
    // Name typed, price left blank → save disabled.
    await userEvent.type(screen.getByLabelText("Serving size 1 name"), "4 serve");
    expect(screen.getByRole("button", { name: "Add dish" })).toBeDisabled();
  });

  it("blocks a serving size of 1 (single serve is the base price)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 200 }))));
    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Biryani");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "20");
    await userEvent.click(screen.getByRole("button", { name: /add serving size/i }));
    await userEvent.type(screen.getByLabelText("Serving size 1 name"), "1 serve");
    await userEvent.type(screen.getByLabelText("Serving size 1 price"), "20");
    expect(screen.getByRole("button", { name: "Add dish" })).toBeDisabled();
    expect(screen.getByText(/must be 2 or more/i)).toBeInTheDocument();
  });

  it("drink category shows Sizes editor and allows Large/Small (no 2+ rule)", async () => {
    let posted: any = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") {
          posted = JSON.parse(init.body as string);
          return Promise.resolve(new Response(JSON.stringify({ id: 7 }), { status: 200 }));
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      }),
    );
    const drink = {
      id: 7, dish_number: 300, name: "Lemon Mint", price_aed: "10.00",
      category: "Drinks", description: null, is_available: true, variants: [],
    } as any;
    render(
      <DishEditModal
        menuId={5}
        dish={drink}
        categories={[]}
        nextNumber={301}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );

    // Editor reads "Sizes", not "Serving sizes".
    expect(screen.getByText("Sizes")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /add size/i }));
    await userEvent.type(screen.getByLabelText("Size 1 name"), "Large");
    await userEvent.type(screen.getByLabelText("Size 1 price"), "12");

    // No 2+ rule for drinks → no error, save enabled, "Large" submits.
    expect(screen.queryByText(/must be 2 or more/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.variants).toEqual([{ name: "Large", price_aed: "12" }]);
  });
});
