// desktop/src/main/main.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("electron", () => {
  class FakeBrowserWindow {
    loadedUrl: string | undefined;
    loadURL(url: string) {
      this.loadedUrl = url;
    }
    once(_ev: string, cb: () => void) {
      cb();
    }
    show() {}
    focus() {}
    setMenuBarVisibility(_v: boolean) {}
  }
  return { BrowserWindow: FakeBrowserWindow };
});

import { createMainWindow } from "./main";

describe("createMainWindow", () => {
  it("loads the given URL into a BrowserWindow", () => {
    const win = createMainWindow("http://localhost:5173");
    expect((win as unknown as { loadedUrl: string }).loadedUrl).toBe(
      "http://localhost:5173",
    );
  });
});
