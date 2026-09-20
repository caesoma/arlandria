import { createHash, randomUUID } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

export const hash = (data: string | Buffer) => createHash("sha256").update(data).digest("hex");
export const json = (value: unknown) => JSON.stringify(value, null, 2) + "\n";
export const readJson = (path: string): unknown => JSON.parse(readFileSync(path, "utf8"));

export function inside(root: string, path: string): string {
  if (isAbsolute(path)) throw new Error("Artifact paths must be relative");
  const base = realpathSync(root);
  const result = resolve(base, path);
  const rel = relative(base, result);
  if (!rel || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel))
    throw new Error("Artifact path escapes its root");
  let current = base;
  for (const part of rel.split(sep)) {
    current = resolve(current, part);
    if (existsSync(current) && lstatSync(current).isSymbolicLink())
      throw new Error("Symlinks are not accepted for artifacts");
  }
  return result;
}

export function atomicWrite(path: string, data: string | Buffer) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${randomUUID()}.partial`;
  writeFileSync(temporary, data, { flag: "wx", mode: 0o600 });
  renameSync(temporary, path);
}
