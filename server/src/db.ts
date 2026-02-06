import { Pool } from "pg";
import { config } from "./config.js";
import { logger } from "./logger.js";

export const pool = new Pool({
  host: config.db.host,
  port: config.db.port,
  user: config.db.user,
  password: config.db.password,
  database: config.db.name,
});

pool.on("error", (err) => {
  logger.error("db.error", { error: err.message });
});
