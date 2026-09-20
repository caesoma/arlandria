// Recommended by Norma — fixed with Claude via Devin
// Vitest picks up *.spec.mjs only; *.test.mjs stays on the node:test runner (`npm run test:node`).
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.spec.mjs"],
    environment: "node",
    testTimeout: 60_000,
  },
});
