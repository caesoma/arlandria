import { fileURLToPath } from "node:url";

export const banner = String.raw`
 ▇▇▇▇▇  ▇▇▇▇▇▇  ▇▇       ▇▇▇▇▇  ▇▇   ▇▇ ▇▇▇▇▇▇  ▇▇▇▇▇▇  ▇▇▇▇▇▇▇  ▇▇▇▇▇
▇▇   ▇▇ ▇▇   ▇▇ ▇▇      ▇▇   ▇▇ ▇▇▇  ▇▇ ▇▇   ▇▇ ▇▇   ▇▇   ▇▇▇   ▇▇   ▇▇
▇▇▇▇▇▇▇ ▇▇▇▇▇▇  ▇▇      ▇▇▇▇▇▇▇ ▇▇ ▇ ▇▇ ▇▇   ▇▇ ▇▇▇▇▇▇    ▇▇▇   ▇▇▇▇▇▇▇
▇▇   ▇▇ ▇▇  ▇▇  ▇▇      ▇▇   ▇▇ ▇▇  ▇▇▇ ▇▇   ▇▇ ▇▇  ▇▇    ▇▇▇   ▇▇   ▇▇
▇▇   ▇▇ ▇▇   ▇▇ ▇▇▇▇▇▇▇ ▇▇   ▇▇ ▇▇   ▇▇ ▇▇▇▇▇▇  ▇▇   ▇▇ ▇▇▇▇▇▇▇ ▇▇   ▇▇
`;

<<<<<<< HEAD
// Canonical exports the launcher (bin/arlandria.js) and logo.d.mts expect.
// Derived from `banner` so the art isn't duplicated; trim the template's leading/trailing newline.
export const ARLANDRIA_ASCII_LOGO = banner.replace(/^\n+|\n+$/g, "").split("\n");
export const ARLANDRIA_ASCII_LOGO_TEXT = ARLANDRIA_ASCII_LOGO.join("\n");
export const ARLANDRIA_LOGO_HTML = `<style>@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');.logo{width:auto!important;height:auto!important;margin-bottom:16px!important}</style><span style="font-family:'VT323',monospace;font-size:48px;color:#c8a45c">arlandria</span>`;

export default ARLANDRIA_ASCII_LOGO_TEXT;

// print when run directly
import { fileURLToPath } from 'node:url';
=======
export const ARLANDRIA_ASCII_LOGO = banner.replace(/^\n+|\n+$/g, "").split("\n");
export const ARLANDRIA_ASCII_LOGO_TEXT = ARLANDRIA_ASCII_LOGO.join("\n");
export const ARLANDRIA_LOGO_HTML = `<style>@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');.logo{width:auto!important;height:auto!important;margin-bottom:16px!important}</style><span style="font-family:'VT323',monospace;font-size:48px;color:#c8a45c">ARLANDRIA</span>`;

export default ARLANDRIA_ASCII_LOGO_TEXT;

>>>>>>> devin/1789827103-hypathia
if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(ARLANDRIA_ASCII_LOGO_TEXT);
