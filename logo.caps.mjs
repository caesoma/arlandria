// ΚΑΛΛΙΜΑΧΟΣ — uppercase Greek (ansi_regular block lettering)
// Six letters reuse ansi_regular (Κ Α Ι Μ Ο Χ = K A I M O X); only Λ and Σ are hand-drawn.
// Preview:  node logo.caps.mjs
export const banner = String.raw`
██   ██  █████     ██      ██   ██ ███    ███  █████  ██   ██  ██████  ███████
██  ██  ██   ██   ████    ████  ██ ████  ████ ██   ██  ██ ██  ██    ██ ███
█████   ███████  ██ ██   ██ ██  ██ ██ ████ ██ ███████   ███   ██    ██   ███
██  ██  ██   ██ ██   ██ ██   ██ ██ ██  ██  ██ ██   ██  ██ ██  ██    ██ ███
██   ██ ██   ██ ██   ██ ██   ██ ██ ██      ██ ██   ██ ██   ██  ██████  ███████
`;

export default banner;

// print when run directly
import { fileURLToPath } from 'node:url';
if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(banner);
