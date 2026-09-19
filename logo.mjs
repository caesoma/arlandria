// Καλλίμαχος — lowercase Greek (hand-drawn to match ansi_regular weight)
// Every glyph hand-drawn: tonos on the ί, descenders on μ/χ/ς, final-sigma ς. Initial Κ reused.
// Preview:  node logo.mjs
export const banner = String.raw`
██  ▄█▀             ▀█▄        ▀█▄      ▄▀
██▄█▀     ▄▄▄ ▄▄     ▀█▄        ▀█▄     ▄▄    ▄▄  ▄▄    ▄▄▄ ▄▄ ▄▄      ▄   ▄▄▄▄▄    ▄▄▄▄▄
███▄     ██  ██     ██▀█▄      ██▀█▄    ██    ██  ██   ██  ██   ▀█▄  ▄█▀  ██   ██  ██   ▀▀
██ ▀█▄   ██  ██    ██  ▀█▄    ██  ▀█▄   ██    ██  ██   ██  ██    ▀█▄▄█▀   ██   ██  ▀█▄▄▄▄
██   ██  ▀█▄▄▀█▄  ██    ▀█▄  ██    ▀█▄  ▀█▄▄  ██▀▄█▀▄  ▀█▄▄▀█▄   ▄█▀▀█▄   ▀█▄▄▄█▀       ██
                                              ██                ▄█▀  ▀█▄               ▀▀
                                              ▀▀                ▀      ▀▀
`;

// Canonical exports the launcher (bin/callimachus.js) and logo.d.mts expect.
// Derived from `banner` so the art isn't duplicated; trim the template's leading/trailing newline.
export const CALLIMACHUS_ASCII_LOGO = banner.replace(/^\n+|\n+$/g, "").split("\n");
export const CALLIMACHUS_ASCII_LOGO_TEXT = CALLIMACHUS_ASCII_LOGO.join("\n");
export const CALLIMACHUS_LOGO_HTML = `<style>@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');.logo{width:auto!important;height:auto!important;margin-bottom:16px!important}</style><span style="font-family:'VT323',monospace;font-size:48px;color:#c8a45c">callimachus</span>`;

export default CALLIMACHUS_ASCII_LOGO_TEXT;

// print when run directly
import { fileURLToPath } from 'node:url';
if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(CALLIMACHUS_ASCII_LOGO_TEXT);
