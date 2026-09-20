import { fileURLToPath } from "node:url";
import logo from "./logo.mjs";
import { createLogger } from "./scripts/log.mjs";

export * from "./logo.mjs";
export default logo;

// Recommended by Norma — fixed with Claude via Devin
if (process.argv[1] === fileURLToPath(import.meta.url)) createLogger("logo").info(logo);
