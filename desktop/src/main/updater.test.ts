import { describe, it, expect, vi } from "vitest";
import { initAutoUpdater } from "./updater";

describe("initAutoUpdater", () => {
  it("checks for updates and notifies via the injected updater", () => {
    const checkForUpdatesAndNotify = vi.fn();
    const fakeAutoUpdater = {
      checkForUpdatesAndNotify,
      on: vi.fn(),
    };

    initAutoUpdater(fakeAutoUpdater as never);

    expect(checkForUpdatesAndNotify).toHaveBeenCalledTimes(1);
  });

  it("registers an error listener so a failed check never crashes the app", () => {
    const on = vi.fn();
    const fakeAutoUpdater = {
      checkForUpdatesAndNotify: vi.fn(),
      on,
    };

    initAutoUpdater(fakeAutoUpdater as never);

    expect(on).toHaveBeenCalledWith("error", expect.any(Function));
  });
});
