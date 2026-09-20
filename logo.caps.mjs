import { fileURLToPath } from "node:url";
import logo from "./logo.mjs";

export * from "./logo.mjs";
export default logo;

if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(logo);
