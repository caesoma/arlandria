import { fileURLToPath } from "node:url";
import { createLogger } from "./scripts/log.mjs";

export const banner = String.raw`
 ▇▇▇▇▇  ▇▇▇▇▇▇  ▇▇       ▇▇▇▇▇  ▇▇   ▇▇ ▇▇▇▇▇▇  ▇▇▇▇▇▇  ▇▇▇▇▇▇▇  ▇▇▇▇▇
▇▇   ▇▇ ▇▇   ▇▇ ▇▇      ▇▇   ▇▇ ▇▇▇  ▇▇ ▇▇   ▇▇ ▇▇   ▇▇   ▇▇▇   ▇▇   ▇▇
▇▇▇▇▇▇▇ ▇▇▇▇▇▇  ▇▇      ▇▇▇▇▇▇▇ ▇▇ ▇ ▇▇ ▇▇   ▇▇ ▇▇▇▇▇▇    ▇▇▇   ▇▇▇▇▇▇▇
▇▇   ▇▇ ▇▇  ▇▇  ▇▇      ▇▇   ▇▇ ▇▇  ▇▇▇ ▇▇   ▇▇ ▇▇  ▇▇    ▇▇▇   ▇▇   ▇▇
▇▇   ▇▇ ▇▇   ▇▇ ▇▇▇▇▇▇▇ ▇▇   ▇▇ ▇▇   ▇▇ ▇▇▇▇▇▇  ▇▇   ▇▇ ▇▇▇▇▇▇▇ ▇▇   ▇▇
`;

export const ARLANDRIA_ASCII_LOGO = banner.replace(/^\n+|\n+$/g, "").split("\n");
export const ARLANDRIA_ASCII_LOGO_TEXT = ARLANDRIA_ASCII_LOGO.join("\n");
export const ARLANDRIA_LOGO_HTML = `<style>@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');.logo{width:auto!important;height:auto!important;margin-bottom:16px!important}</style><span style="font-family:'VT323',monospace;font-size:48px;color:#c8a45c">ARLANDRIA</span>`;

export default ARLANDRIA_ASCII_LOGO_TEXT;

// Recommended by Norma — fixed with Claude via Devin
if (process.argv[1] === fileURLToPath(import.meta.url)) createLogger("logo").info(ARLANDRIA_ASCII_LOGO_TEXT);
