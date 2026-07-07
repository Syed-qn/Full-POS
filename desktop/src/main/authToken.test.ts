import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";
import { getAuthToken, setAuthToken, initAuthTokenStore } from "./authToken";

describe("authToken store (in-memory only, no persistence path set)", () => {
  beforeEach(() => setAuthToken(""));

  it("returns empty string before any token is set", () => {
    expect(getAuthToken()).toBe("");
  });

  it("returns the most recently set token", () => {
    setAuthToken("tok-abc");
    expect(getAuthToken()).toBe("tok-abc");
    setAuthToken("tok-xyz");
    expect(getAuthToken()).toBe("tok-xyz");
  });
});

describe("authToken store persistence", () => {
  const tmpFiles: string[] = [];

  afterEach(() => {
    for (const f of tmpFiles.splice(0)) fs.rmSync(f, { force: true });
  });

  it("persists a set token to disk and reloads it on init (survives app restart)", () => {
    const file = path.join(os.tmpdir(), `authtoken-${Date.now()}.txt`);
    tmpFiles.push(file);

    initAuthTokenStore(file);
    setAuthToken("persisted-tok");
    expect(fs.readFileSync(file, "utf8")).toBe("persisted-tok");

    // Simulate a fresh app process reading the same file back on next launch.
    initAuthTokenStore(file);
    expect(getAuthToken()).toBe("persisted-tok");
  });

  it("starts with an empty token when the persistence file doesn't exist yet", () => {
    const file = path.join(os.tmpdir(), `authtoken-missing-${Date.now()}.txt`);
    initAuthTokenStore(file);
    expect(getAuthToken()).toBe("");
  });
});
