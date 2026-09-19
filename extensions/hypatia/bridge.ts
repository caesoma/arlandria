import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Type, type TSchema } from "typebox";

const script = fileURLToPath(new URL("../../skills/hypatia/scripts/hypatia.py", import.meta.url));
const schemas: Record<string, TSchema> = JSON.parse(readFileSync(
  fileURLToPath(new URL("../../skills/hypatia/references/schemas.json", import.meta.url)), "utf8"));

export const EvidenceSchema = Type.Unsafe<Record<string, unknown>>(schemas.Evidence);
export type Gate = "criteria" | "triage" | "curation";
export interface Snapshot {
  root: string;
  directory: string;
  handoff: { revision: string };
  ledger: { question: string };
}
export interface Request {
  status: string;
  question: string;
  previous_revision?: string;
}
export type Operation =
  | "prepare" | "request-read" | "request-write" | "pause" | "gate-fingerprint" | "approve-gate" | "finalize"
  | "load-snapshot" | "snapshot" | "source" | "context" | "context-save" | "evidence" | "save" | "render"
  | "evidence-directory" | "evidence-digest" | "validate" | "beamer" | "shortlist" | "inside" | "schema";

export function python<T = unknown>(operation: Operation, root: string, payload: unknown = {}, revision?: string): T {
  const result = spawnSync("uv", [
    "run", "--script", script, operation, root, ...(revision ? ["--revision", revision] : []),
  ], {
    input: JSON.stringify(payload), encoding: "utf8", maxBuffer: 64 * 1024 * 1024,
    env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1" },
  });
  if (result.error) throw new Error(`Cannot run Python skill script: ${result.error.message}`);
  if (result.status !== 0) {
    let message = result.stderr || result.stdout || `Python exited with status ${result.status}`;
    try {
      const body: unknown = JSON.parse(result.stdout);
      if (typeof body === "object" && body !== null && "error" in body && typeof body.error === "string")
        message = body.error;
    } catch { /* Preserve subprocess diagnostics when no JSON response was produced. */ }
    throw new Error(message);
  }
  return JSON.parse(result.stdout) as T;
}

export const loadSnapshot = (root: string, revision?: string) =>
  python<Snapshot>("load-snapshot", root, {}, revision);
export const evidenceDirectory = (snapshot: Snapshot) =>
  python<string>("evidence-directory", snapshot.root, {}, snapshot.handoff.revision);
export const render = (snapshot: Snapshot) =>
  python<string>("render", snapshot.root, {}, snapshot.handoff.revision);
export const pauseRequest = (root: string, question: string) => python("pause", root, { question });
