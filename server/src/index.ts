import express from "express";
import type { Request, Response, NextFunction } from "express";
import cors from "cors";
import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import crypto from "node:crypto";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { config } from "./config.js";
import { pool } from "./db.js";
import { embedText } from "./ollama.js";
import { logger } from "./logger.js";

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));
app.use((req: Request, res: Response, next: NextFunction) => {
  const start = Date.now();
  const requestId = crypto.randomUUID();
  (req as any).requestId = requestId;
  logger.info("http.request", {
    id: requestId,
    method: req.method,
    path: req.path,
  });
  res.on("finish", () => {
    logger.info("http.response", {
      id: requestId,
      method: req.method,
      path: req.path,
      status: res.statusCode,
      ms: Date.now() - start,
    });
  });
  next();
});

interface ToolDef {
  name: string;
  description: string;
  parameters: z.ZodTypeAny;
  execute: (params: any) => Promise<any>;
}

const tools: ToolDef[] = [];

function addTool(tool: ToolDef) {
  tools.push(tool);
}

function findTool(name: string) {
  return tools.find((t) => t.name === name);
}

function vectorToSql(vector: number[]): string {
  return `[${vector.join(",")}]`;
}

const authMiddleware = (req: any, res: any, next: any) => {
  if (!config.mcpHttpToken) return next();
  const token = req.headers.authorization?.replace("Bearer ", "");
  if (token !== config.mcpHttpToken) {
    return res.status(401).json({ error: "unauthorized" });
  }
  return next();
};

app.get("/health", (_req: Request, res: Response) => {
  res.json({
    status: "ok",
    version: "26.02.4",
    time: new Date().toISOString(),
  });
});

app.get("/tools", authMiddleware, (_req: Request, res: Response) => {
  res.json(
    tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: (zodToJsonSchema as any)(t.parameters, t.name),
    }))
  );
});

app.post("/tools/:name", authMiddleware, async (req: Request, res: Response) => {
  const requestId = (req as any).requestId;
  const tool = findTool(req.params.name);
  if (!tool) return res.status(404).json({ error: "tool not found" });
  const parsed = tool.parameters.safeParse(req.body || {});
  if (!parsed.success) {
    logger.warn("http.tool.invalid", {
      id: requestId,
      tool: req.params.name,
      error: parsed.error.message,
    });
    return res.status(400).json({ error: parsed.error.message });
  }
  try {
    const result = await tool.execute(parsed.data);
    return res.json(result);
  } catch (err: any) {
    logger.error("http.tool.error", {
      id: requestId,
      tool: req.params.name,
      error: err?.message || String(err),
    });
    return res.status(500).json({ error: err?.message || String(err) });
  }
});

// --- Tools ---

addTool({
  name: "channels.list",
  description: "List known channels",
  parameters: z.object({}).optional(),
  execute: async () => {
    const { rows } = await pool.query(
      `SELECT id, username, title, category, is_private, last_fetched_at, last_message_id
       FROM channels
       ORDER BY username`
    );
    return rows;
  },
});

addTool({
  name: "messages.fetch",
  description: "Fetch messages by date/channel/tag",
  parameters: z.object({
    channel: z.string().optional(),
    date_from: z.string().optional(),
    date_to: z.string().optional(),
    tag: z.string().optional(),
    limit: z.number().int().min(1).max(500).optional().default(100),
    offset: z.number().int().min(0).optional().default(0),
  }),
  execute: async (params) => {
    const where: string[] = [];
    const values: any[] = [];
    let idx = 1;

    let joinTag = "";
    if (params.tag) {
      joinTag = "JOIN message_tags mt ON mt.message_id = m.id JOIN tags t ON t.id = mt.tag_id";
      where.push(`t.canonical = $${idx++}`);
      values.push(params.tag);
    }
    if (params.channel) {
      where.push(`c.username = $${idx++}`);
      values.push(params.channel);
    }
    if (params.date_from) {
      where.push(`m.date >= $${idx++}`);
      values.push(params.date_from);
    }
    if (params.date_to) {
      where.push(`m.date <= $${idx++}`);
      values.push(params.date_to);
    }

    const sql = `
      SELECT
        m.id,
        c.username,
        m.message_id,
        m.ts,
        m.date,
        m.permalink,
        m.content,
        m.views,
        m.emoji_line,
        m.code_json,
        (SELECT array_agg(t2.canonical ORDER BY t2.canonical)
           FROM message_tags mt2
           JOIN tags t2 ON t2.id = mt2.tag_id
          WHERE mt2.message_id = m.id) AS tags
      FROM messages m
      JOIN channels c ON c.id = m.channel_id
      ${joinTag}
      ${where.length ? "WHERE " + where.join(" AND ") : ""}
      ORDER BY m.ts DESC
      LIMIT $${idx++} OFFSET $${idx++}
    `;

    values.push(params.limit, params.offset);

    const { rows } = await pool.query(sql, values);
    return rows;
  },
});

addTool({
  name: "tags.top",
  description: "Top tags for a date range",
  parameters: z.object({
    channel: z.string().optional(),
    date_from: z.string().optional(),
    date_to: z.string().optional(),
    limit: z.number().int().min(1).max(200).optional().default(20),
  }),
  execute: async (params) => {
    const where: string[] = [];
    const values: any[] = [];
    let idx = 1;

    if (params.channel) {
      where.push(`c.username = $${idx++}`);
      values.push(params.channel);
    }
    if (params.date_from) {
      where.push(`m.date >= $${idx++}`);
      values.push(params.date_from);
    }
    if (params.date_to) {
      where.push(`m.date <= $${idx++}`);
      values.push(params.date_to);
    }

    const sql = `
      SELECT t.canonical, COUNT(*)::int AS count
      FROM message_tags mt
      JOIN tags t ON t.id = mt.tag_id
      JOIN messages m ON m.id = mt.message_id
      JOIN channels c ON c.id = m.channel_id
      ${where.length ? "WHERE " + where.join(" AND ") : ""}
      GROUP BY t.canonical
      ORDER BY count DESC, t.canonical
      LIMIT $${idx++}
    `;

    values.push(params.limit);
    const { rows } = await pool.query(sql, values);
    return rows;
  },
});

addTool({
  name: "messages.search",
  description: "Semantic search over messages (pgvector + Ollama embeddings)",
  parameters: z.object({
    query: z.string(),
    channel: z.string().optional(),
    date_from: z.string().optional(),
    date_to: z.string().optional(),
    limit: z.number().int().min(1).max(100).optional().default(20),
    min_score: z.number().min(0).max(1).optional(),
  }),
  execute: async (params) => {
    const embedding = await embedText(params.query);
    if (!embedding.length) {
      return [];
    }
    const vector = vectorToSql(embedding);

    const where: string[] = [];
    const values: any[] = [vector];
    let idx = 2;

    if (params.channel) {
      where.push(`c.username = $${idx++}`);
      values.push(params.channel);
    }
    if (params.date_from) {
      where.push(`m.date >= $${idx++}`);
      values.push(params.date_from);
    }
    if (params.date_to) {
      where.push(`m.date <= $${idx++}`);
      values.push(params.date_to);
    }
    if (params.min_score !== undefined) {
      where.push(`1 - (e.embedding <=> $1::vector) >= $${idx++}`);
      values.push(params.min_score);
    }

    const sql = `
      SELECT
        m.id,
        c.username,
        m.message_id,
        m.ts,
        m.date,
        m.permalink,
        m.content,
        (1 - (e.embedding <=> $1::vector)) AS score,
        m.emoji_line,
        m.code_json,
        (SELECT array_agg(t2.canonical ORDER BY t2.canonical)
           FROM message_tags mt2
           JOIN tags t2 ON t2.id = mt2.tag_id
          WHERE mt2.message_id = m.id) AS tags
      FROM embeddings e
      JOIN messages m ON m.id = e.message_id
      JOIN channels c ON c.id = m.channel_id
      ${where.length ? "WHERE " + where.join(" AND ") : ""}
      ORDER BY e.embedding <=> $1::vector
      LIMIT $${idx++}
    `;

    values.push(params.limit);
    const { rows } = await pool.query(sql, values);
    return rows;
  },
});

// --- MCP server wiring ---

const server = new Server(
  { name: "channel-mcp", version: "26.02.4" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  logger.debug("mcp.list_tools");
  return {
    tools: tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: (zodToJsonSchema as any)(t.parameters, t.name),
    })),
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const requestId = crypto.randomUUID();
  logger.info("mcp.tool.call", {
    id: requestId,
    tool: request.params.name,
  });
  const tool = findTool(request.params.name);
  if (!tool) {
    return {
      content: [
        {
          type: "text",
          text: `Unknown tool: ${request.params.name}`,
        },
      ],
      isError: true,
    };
  }
  const parsed = tool.parameters.safeParse(request.params.arguments ?? {});
  if (!parsed.success) {
    return {
      content: [
        {
          type: "text",
          text: `Invalid input: ${parsed.error.message}`,
        },
      ],
      isError: true,
    };
  }
  try {
    const started = Date.now();
    const result = await tool.execute(parsed.data);
    logger.info("mcp.tool.ok", {
      id: requestId,
      tool: request.params.name,
      ms: Date.now() - started,
      result: logger.summarize(result),
    });
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  } catch (err: any) {
    logger.error("mcp.tool.error", {
      id: requestId,
      tool: request.params.name,
      error: err?.message || String(err),
    });
    return {
      content: [
        {
          type: "text",
          text: `Tool error: ${err?.message || String(err)}`,
        },
      ],
      isError: true,
    };
  }
});

async function start() {
  logger.info("startup.config", {
    mcpTransport: config.mcpTransport,
    mcpHost: config.mcpHost,
    mcpPort: config.mcpPort,
    db: config.db,
    ollama: config.ollama,
  });

  if (config.mcpTransport === "stdio") {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    logger.info("mcp.transport.ready", { transport: "stdio" });
  } else {
    logger.warn(
      `[mcp] MCP_TRANSPORT=${config.mcpTransport} not supported; falling back to stdio`
    );
    const transport = new StdioServerTransport();
    await server.connect(transport);
  }

  app.listen(config.mcpPort, config.mcpHost, () => {
    logger.info("http.listen", { host: config.mcpHost, port: config.mcpPort });
  });
}

start().catch((err) => {
  logger.error("startup.error", { error: err?.message || String(err) });
  process.exit(1);
});
