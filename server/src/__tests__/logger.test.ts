import { describe, it, expect } from "vitest";
import { logger } from "../logger.js";

describe("logger.summarize", () => {
  it("returns null/undefined as-is", () => {
    expect(logger.summarize(null)).toBeNull();
    expect(logger.summarize(undefined)).toBeUndefined();
  });

  it("summarizes arrays", () => {
    expect(logger.summarize([1, 2, 3])).toEqual({ type: "array", length: 3 });
    expect(logger.summarize([])).toEqual({ type: "array", length: 0 });
  });

  it("summarizes objects with keys (max 8)", () => {
    const obj = { a: 1, b: 2, c: 3 };
    const result = logger.summarize(obj);
    expect(result).toEqual({ type: "object", keys: ["a", "b", "c"] });
  });

  it("truncates object keys to 8", () => {
    const obj = Object.fromEntries(
      Array.from({ length: 12 }, (_, i) => [`k${i}`, i])
    );
    const result = logger.summarize(obj) as { keys: string[] };
    expect(result.keys).toHaveLength(8);
  });

  it("returns primitives as-is", () => {
    expect(logger.summarize(42)).toBe(42);
    expect(logger.summarize("hello")).toBe("hello");
    expect(logger.summarize(true)).toBe(true);
  });
});
