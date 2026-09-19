import { createHash } from "node:crypto";
import { createJiti } from "jiti";

const { python, loadSnapshot, evidenceDirectory, render } =
  await createJiti(import.meta.url).import("../extensions/hypatia/bridge.ts");
export { python, loadSnapshot, evidenceDirectory, render };
export const hash = data => createHash("sha256").update(data).digest("hex");
export const json = value => JSON.stringify(value, null, 2) + "\n";
export const inside = (root, path) => python("inside", root, { path });
export const approveGate = (root, gate, fingerprint) => python("approve-gate", root, { gate, fingerprint });
export const gateFingerprint = (root, gate) => python("gate-fingerprint", root, { gate });
export const finalize = root => python("finalize", root);
export const saveEvidence = (s, document) => python("save", s.root, document, s.handoff.revision);
export const validateEvidence = (s, evidence, context) => python("validate", s.root, { evidence, context }, s.handoff.revision);
export const evidenceDigest = s => python("evidence-digest", s.root, {}, s.handoff.revision);
export const loadContext = s => python("context", s.root, {}, s.handoff.revision);
export const loadEvidence = s => python("evidence", s.root, {}, s.handoff.revision);
export const beamer = (snapshot, evidence, context) => python("beamer", snapshot.root, { snapshot, evidence, context });
export const shortlist = evidence => python("shortlist", ".", evidence);
