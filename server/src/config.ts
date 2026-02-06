import { config as loadEnv } from "dotenv";

loadEnv();

const int = (value: string | undefined, defaultValue: number) => {
  if (!value) return defaultValue;
  const parsed = parseInt(value, 10);
  return Number.isNaN(parsed) ? defaultValue : parsed;
};

export const config = {
  mcpTransport: process.env.MCP_TRANSPORT || "stdio",
  mcpPort: int(process.env.MCP_PORT, 3333),
  mcpHost: process.env.MCP_HOST || "0.0.0.0",
  mcpHttpToken: process.env.MCP_HTTP_TOKEN || "",

  db: {
    host: process.env.CHANNEL_DB_HOST || "127.0.0.1",
    port: int(process.env.CHANNEL_DB_PORT, 5432),
    user: process.env.CHANNEL_DB_USER || "channel",
    password: process.env.CHANNEL_DB_PASSWORD || "channel_secret",
    name: process.env.CHANNEL_DB_NAME || "channel_mcp",
  },

  ollama: {
    baseUrl: process.env.OLLAMA_BASE_URL || "http://127.0.0.1:11434",
    embedModel: process.env.OLLAMA_EMBED_MODEL || "nomic-embed-text",
  },

  logLevel: process.env.LOG_LEVEL || "info",
};
