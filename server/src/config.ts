import { config as loadEnv } from "dotenv";

loadEnv();

const int = (value: string | undefined, defaultValue: number) => {
  if (!value) return defaultValue;
  const parsed = parseInt(value, 10);
  return Number.isNaN(parsed) ? defaultValue : parsed;
};

const bool = (value: string | undefined, defaultValue: boolean) => {
  if (value === undefined) return defaultValue;
  return ["1", "true", "yes", "y"].includes(value.toLowerCase());
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

  llm: {
    backend: process.env.LLM_BACKEND || "llm_mcp",
    mcpBaseUrl: process.env.LLM_MCP_BASE_URL || "http://llmcore:8080",
    mcpProvider: process.env.LLM_MCP_PROVIDER || "auto",
    fallbackOllama: bool(process.env.LLM_BACKEND_FALLBACK_OLLAMA, true),
    timeoutSec: int(process.env.LLM_BACKEND_TIMEOUT_SEC, 30),
  },

  logLevel: process.env.LOG_LEVEL || "info",
};
