import { describe, it, expect } from "vitest";
import { z } from "zod";

// Воспроизводим Zod-схемы из index.ts для тестирования валидации
const messagesFetchSchema = z.object({
  channel: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
  tag: z.string().optional(),
  limit: z.number().int().min(1).max(500).optional().default(100),
  offset: z.number().int().min(0).optional().default(0),
});

const tagsTopSchema = z.object({
  channel: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
  limit: z.number().int().min(1).max(200).optional().default(20),
});

const messagesSearchSchema = z.object({
  query: z.string(),
  channel: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
  limit: z.number().int().min(1).max(100).optional().default(20),
  min_score: z.number().min(0).max(1).optional(),
});

const channelsListSchema = z.object({}).optional();

describe("Zod schema: messages.fetch", () => {
  it("accepts empty params (all optional)", () => {
    const result = messagesFetchSchema.safeParse({});
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.limit).toBe(100);
      expect(result.data.offset).toBe(0);
    }
  });

  it("accepts full params", () => {
    const result = messagesFetchSchema.safeParse({
      channel: "test_channel",
      date_from: "2026-01-01",
      date_to: "2026-02-01",
      tag: "crypto",
      limit: 50,
      offset: 10,
    });
    expect(result.success).toBe(true);
  });

  it("rejects limit > 500", () => {
    const result = messagesFetchSchema.safeParse({ limit: 501 });
    expect(result.success).toBe(false);
  });

  it("rejects limit < 1", () => {
    const result = messagesFetchSchema.safeParse({ limit: 0 });
    expect(result.success).toBe(false);
  });

  it("rejects negative offset", () => {
    const result = messagesFetchSchema.safeParse({ offset: -1 });
    expect(result.success).toBe(false);
  });

  it("rejects non-integer limit", () => {
    const result = messagesFetchSchema.safeParse({ limit: 1.5 });
    expect(result.success).toBe(false);
  });
});

describe("Zod schema: tags.top", () => {
  it("applies default limit=20", () => {
    const result = tagsTopSchema.safeParse({});
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.limit).toBe(20);
    }
  });

  it("rejects limit > 200", () => {
    const result = tagsTopSchema.safeParse({ limit: 201 });
    expect(result.success).toBe(false);
  });
});

describe("Zod schema: messages.search", () => {
  it("requires query field", () => {
    const result = messagesSearchSchema.safeParse({});
    expect(result.success).toBe(false);
  });

  it("accepts valid search params", () => {
    const result = messagesSearchSchema.safeParse({
      query: "bitcoin price",
      limit: 10,
      min_score: 0.5,
    });
    expect(result.success).toBe(true);
  });

  it("rejects min_score > 1", () => {
    const result = messagesSearchSchema.safeParse({
      query: "test",
      min_score: 1.5,
    });
    expect(result.success).toBe(false);
  });

  it("rejects min_score < 0", () => {
    const result = messagesSearchSchema.safeParse({
      query: "test",
      min_score: -0.1,
    });
    expect(result.success).toBe(false);
  });
});

describe("Zod schema: channels.list", () => {
  it("accepts empty object", () => {
    const result = channelsListSchema.safeParse({});
    expect(result.success).toBe(true);
  });

  it("accepts undefined", () => {
    const result = channelsListSchema.safeParse(undefined);
    expect(result.success).toBe(true);
  });
});

// Воспроизводим паттерн tool registry
describe("tool registry pattern", () => {
  interface ToolDef {
    name: string;
    description: string;
    parameters: z.ZodTypeAny;
  }

  const tools: ToolDef[] = [
    { name: "channels.list", description: "List channels", parameters: channelsListSchema },
    { name: "messages.fetch", description: "Fetch messages", parameters: messagesFetchSchema },
    { name: "tags.top", description: "Top tags", parameters: tagsTopSchema },
    { name: "messages.search", description: "Search messages", parameters: messagesSearchSchema },
  ];

  function findTool(name: string) {
    return tools.find((t) => t.name === name);
  }

  it("finds existing tool by name", () => {
    expect(findTool("channels.list")).toBeDefined();
    expect(findTool("messages.fetch")?.name).toBe("messages.fetch");
  });

  it("returns undefined for unknown tool", () => {
    expect(findTool("nonexistent.tool")).toBeUndefined();
  });

  it("all tools have name, description, parameters", () => {
    for (const tool of tools) {
      expect(tool.name).toBeTruthy();
      expect(tool.description).toBeTruthy();
      expect(tool.parameters).toBeDefined();
    }
  });

  it("all tool names are unique", () => {
    const names = tools.map((t) => t.name);
    expect(new Set(names).size).toBe(names.length);
  });
});
