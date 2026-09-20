// Recommended by Norma — fixed with Claude via Devin
// Lightweight structured logger for the launcher and logo scripts: levels, ISO timestamp,
// component tag, optional metadata. Level threshold comes from ARLANDRIA_LOG_LEVEL
// (debug|info|warn|error; default info). warn/error go to stderr, the rest to stdout.
const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

function threshold() {
  const configured = process.env.ARLANDRIA_LOG_LEVEL;
  return configured && configured in LEVELS ? LEVELS[configured] : LEVELS.info;
}

function format(level, component, message, meta) {
  const header = `${new Date().toISOString()} ${level.toUpperCase()} [${component}]`;
  const context = meta && Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : "";
  return message.includes("\n") ? `${header}${context}\n${message}\n` : `${header} ${message}${context}\n`;
}

export function createLogger(component) {
  const emit = (level, message, meta) => {
    if (LEVELS[level] < threshold()) return;
    const stream = LEVELS[level] >= LEVELS.warn ? process.stderr : process.stdout;
    stream.write(format(level, component, String(message), meta));
  };
  return {
    debug: (message, meta) => emit("debug", message, meta),
    info: (message, meta) => emit("info", message, meta),
    warn: (message, meta) => emit("warn", message, meta),
    error: (message, meta) => emit("error", message, meta),
  };
}
