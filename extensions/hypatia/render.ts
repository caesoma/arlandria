import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { evidenceDigest, evidenceDirectory, loadContext, loadEvidence, validateDelivery } from "./evidence.js";
import { loadSnapshot, type Snapshot } from "./handoff.js";
import { atomicWrite, inside, json } from "./storage.js";
import type { Evidence, ResearchContext } from "./schema.js";

const md = (value: string) => value.replace(/[\\`*_{}[\]()<>#|!]/g, "\\$&").replace(/\r?\n/g, " ");
const xml = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const cites = (ids: string[]) => ids.map(id => `[${id}](#claim-${id})`).join(", ");

export function shortlist(evidence: Evidence) {
  return evidence.opportunities.filter(o => o.feasibility.effort === "low" &&
    ["open-in-reviewed-corpus", "partly-addressed"].includes(evidence.gaps.find(g => g.id === o.gap_id)!.status));
}

function opportunityText(evidence: Evidence, opportunity: Evidence["opportunities"][number]): string {
  return opportunity.direction_claim_ids.map(id => evidence.claims.find(c => c.id === id)!.statement).join("; ");
}

export function report(snapshot: Snapshot, evidence: Evidence, context: ResearchContext): string {
  const { handoff, ledger } = snapshot;
  const lines = [
    `# Hypatia — ${md(ledger.question)}`, "",
    `Audience: ${md(context.audience)}. Search cutoff: **${handoff.cutoff}**.`,
    `Callimachus revision: \`${handoff.revision}\`. Final included publications: **${handoff.included_ids.length}**.`,
    "Publication counts are not independent-study counts or evidence-quality scores.", "",
    "## Executive summary", "",
    ...evidence.findings.slice(0, 5).map(f => `- ${md(f.statement)} (${cites(f.claim_ids)})`),
    evidence.findings.length ? "" : "No supported findings were established.",
    `${shortlist(evidence).length} direction(s) meet the stated low-effort criteria. Feasibility is Hypatia's assessment, not an author claim.`,
    "", "## Scope and methods", "",
    `Include: ${ledger.criteria.include.map(md).join("; ") || "None specified"}.`,
    `Exclude: ${ledger.criteria.exclude.map(md).join("; ") || "None specified"}.`,
    `Callimachus recorded ${ledger.queries.length} query audit entries and ${ledger.records.length} deduplicated records. All abstract screening and required human curation dispositions are complete.`,
    "The complete search audit and screening decisions are in the pinned Callimachus ledger. No additional search was performed by Hypatia.",
    "", "## Main findings and disagreements", "",
  ];
  for (const finding of evidence.findings) lines.push(
    `### ${finding.id}: ${md(finding.statement)}`, "",
    `Evidence: ${cites(finding.claim_ids)}. Appraisal: ${md(finding.strength)}.`,
    `Disagreement / counterevidence: ${finding.disagreements.length ? cites(finding.disagreements) : "none recorded; this does not establish consensus"}.`, "",
  );
  lines.push("## Literature-identified gaps", "");
  for (const gap of evidence.gaps) lines.push(
    `### ${gap.id}: ${md(gap.statement)}`, "",
    `Status: **${gap.status}**. Evidence: ${cites(gap.claim_ids)}.`,
    `Currency assessment: ${md(gap.currency.rationale)} (${gap.currency.checked_source_ids.length}/${handoff.included_ids.length} included publications checked).`,
    `Subsequent evidence: ${cites(gap.currency.claim_ids) || "none recorded"}.`, "",
  );
  lines.push("An open gap is scoped to this completed corpus and its cutoff; it is not proof of absence across the field.", "",
    "## Low-hanging fruit under stated constraints", "");
  if (!shortlist(evidence).length) lines.push("No directions can currently be shortlisted with adequate evidence and known resources.", "");
  for (const opportunity of shortlist(evidence)) lines.push(
    `- **${opportunity.id}** — ${md(opportunityText(evidence, opportunity))} (${cites(opportunity.direction_claim_ids)}); see the assessment below.`, "",
  );
  lines.push("## All author-proposed directions and feasibility", "");
  for (const opportunity of evidence.opportunities) lines.push(
    `### ${opportunity.id}: ${md(opportunityText(evidence, opportunity))}`, "",
    `Author-proposal evidence: ${cites(opportunity.direction_claim_ids)}. Gap: ${opportunity.gap_id}.`,
    `Hypatia effort assessment: **${opportunity.feasibility.effort}** — ${md(opportunity.feasibility.rationale)}.`,
    `Prerequisites: ${opportunity.feasibility.prerequisites.map(md).join("; ") || "unknown"}.`,
    `Unknowns: ${opportunity.feasibility.unknowns.map(md).join("; ") || "none recorded"}.`,
    `Researcher resource references: ${opportunity.feasibility.resource_ids.join(", ") || "none; feasibility remains unestablished"}.`, "",
  );
  lines.push("## Researcher constraints", "",
    ...context.resources.map(r => `- ${r.id}: ${md(r.description)}`),
    context.resources.length ? "" : "No resources supplied; low-effort shortlisting is disabled.", "",
    "## Coverage, access, and unresolved evidence", "");
  for (const source of handoff.sources) lines.push(
    `- ${md(source.record_id)}: ${source.kind}${source.limitation ? ` — ${md(source.limitation)}` : ""}. ${source.warnings.map(md).join(" ")}`,
  );
  for (const review of evidence.source_reviews) lines.push(`- ${md(review.source_id)} — ${review.status}: ${md(review.note)}`);
  for (const claim of evidence.claims.filter(c => c.verification.status !== "supported"))
    lines.push(`- ${claim.id}: **${claim.verification.status}** — ${md(claim.verification.reason)}.`);
  lines.push("", "## References", "");
  for (const record of ledger.records.filter(r => handoff.included_ids.includes(r.id)))
    lines.push(`- **${md(record.id)}**: ${md(record.authors.join(", "))}. ${md(record.title)} (${record.year ?? "year unknown"}). DOI: ${md(record.doi ?? "unavailable")}.`);
  lines.push("", "## Claim-to-source audit", "",
    "Exact quotation matching checks provenance. Semantic support and scientific strength remain explicit, reviewable assessments.", "");
  for (const claim of evidence.claims) {
    const source = handoff.sources.find(s => s.record_id === claim.source_id)!;
    lines.push(
      `<a id="claim-${claim.id}"></a>`, `### ${claim.id} — ${claim.kind}`, "",
      `${md(claim.statement)}`, "",
      `> ${md(claim.quote)}`, "",
      `Source: ${md(claim.source_id)}, ${source.kind === "abstract" ? "abstract" : `PDF page ${claim.page}`}; artifact \`${source.artifact}\`.`,
      `Verification: **${claim.verification.status}** — ${md(claim.verification.reason)}.`,
      `Appraisal: ${md(claim.appraisal)}. Independent-study identity: ${md(claim.study_id ?? "unknown")}.`, "",
    );
  }
  return lines.join("\n") + "\n";
}

function wrap(value: string, width = 110): string[] {
  return value.match(new RegExp(`.{1,${width}}(?:\\s|$)|.{1,${width}}`, "g"))?.map(s => s.trim()) ?? [""];
}

export function svg(title: string, description: string, rows: string[]): string {
  const lines = [title, description, ...rows.flatMap(row => [...wrap(row), ""])];
  const content = lines.map((line, i) =>
    `<text x="24" y="${38 + i * 25}" font-size="${i === 0 ? 22 : 15}">${xml(line)}</text>`).join("\n");
  return `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title description" viewBox="0 0 1150 ${70 + lines.length * 25}">
<title id="title">${xml(title)}</title><desc id="description">${xml(description)}</desc>
<rect width="100%" height="100%" fill="white"/><g fill="#172b4d" font-family="sans-serif">${content}</g></svg>\n`;
}

export function tableSvg(title: string, description: string, columns: { label: string; width: number }[], rows: string[][]): string {
  const elements: string[] = [];
  let y = 125;
  for (const [index, row] of [columns.map(c => c.label), ...rows].entries()) {
    const cells = row.map((value, i) => wrap(value, Math.max(8, Math.floor((columns[i].width - 24) / 8.5))));
    const height = Math.max(...cells.map(lines => lines.length)) * 23 + 24;
    let x = 25;
    for (const [i, lines] of cells.entries()) {
      elements.push(`<rect x="${x}" y="${y}" width="${columns[i].width}" height="${height}" fill="${index === 0 ? "#e6edf5" : index % 2 ? "#ffffff" : "#f4f7fb"}" stroke="#bdcbdc"/>`);
      for (const [line, value] of lines.entries())
        elements.push(`<text x="${x + 12}" y="${y + 26 + line * 23}" font-weight="${index === 0 ? 600 : 400}">${xml(value)}</text>`);
      x += columns[i].width;
    }
    y += height;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title description" viewBox="0 0 1150 ${y + 35}">
<title id="title">${xml(title)}</title><desc id="description">${xml(description)}</desc>
<rect width="100%" height="100%" fill="white"/>
<g fill="#172b4d" font-family="sans-serif" font-size="15">
<text x="25" y="38" font-size="24" font-weight="600">${xml(title)}</text>
${wrap(description, 115).map((line, i) => `<text x="25" y="${67 + i * 22}">${xml(line)}</text>`).join("\n")}
${elements.join("\n")}</g></svg>\n`;
}

export function render(snapshot: Snapshot): string {
  loadSnapshot(snapshot.root, snapshot.handoff.revision);
  const evidence = loadEvidence(snapshot);
  const context = loadContext(snapshot);
  validateDelivery(snapshot, evidence);
  const digest = evidenceDigest(snapshot);
  const root = evidenceDirectory(snapshot);
  const directory = inside(root, `exports/${digest}`);
  if (existsSync(directory)) {
    atomicWrite(inside(root, "delivery.json"), json({ digest, directory }));
    return directory;
  }
  const staging = inside(root, `exports/${digest}.${randomUUID()}.partial`);
  mkdirSync(staging, { recursive: true });
  const save = (name: string, data: string | Buffer) => writeFileSync(join(staging, name), data, { flag: "wx" });
  save("report.md", report(snapshot, evidence, context));
  save("brief.md", [
    `# ${md(snapshot.ledger.question)}`, `Search cutoff: ${snapshot.handoff.cutoff}; revision: ${snapshot.handoff.revision}.`,
    "", "## Findings", ...evidence.findings.map(f => `- ${md(f.statement)} (${f.claim_ids.join(", ")}; see report audit). Strength: ${md(f.strength)}. Counterevidence: ${f.disagreements.join(", ") || "none recorded"}.`),
    "", "## Gaps", ...evidence.gaps.map(g => `- ${md(g.statement)} — ${g.status} (${g.claim_ids.join(", ")}).`),
    "", "## Feasible author-proposed directions",
    ...shortlist(evidence).map(o => `- ${md(opportunityText(evidence, o))} (${o.direction_claim_ids.join(", ")}). Hypatia feasibility assessment: ${md(o.feasibility.rationale)}.`),
    shortlist(evidence).length ? "" : "No adequately supported low-effort shortlist.",
    "", "## Limitations", "This summary inherits the report's corpus cutoff, access limitations, uncertainty, and researcher constraints.",
    ...snapshot.handoff.sources.filter(s => s.limitation).map(s => `- ${md(s.record_id)}: ${md(s.limitation)}`),
    ...evidence.claims.filter(c => c.verification.status !== "supported").map(c => `- ${c.id}: ${c.verification.status} — ${md(c.verification.reason)}`),
  ].join("\n") + "\n");
  const caption = `Cutoff ${snapshot.handoff.cutoff}. ${snapshot.handoff.included_ids.length} included publications; counts are not evidence strength.`;
  const cells = (sourceId: string, kinds: string[]) => evidence.claims
    .filter(c => c.source_id === sourceId && kinds.includes(c.kind))
    .map(c => `${c.id} (${c.verification.status})`).join("; ") || "No extracted claims";
  save("evidence-matrix.svg", tableSvg("Evidence matrix — claim IDs and verification status", caption, [
    { label: "Publication / access", width: 240 }, { label: "Findings", width: 215 },
    { label: "Gaps / limitations", width: 215 }, { label: "Author proposals", width: 215 },
    { label: "Context", width: 215 },
  ], snapshot.handoff.sources.map(s => [
    `${s.record_id} [${s.kind}]`, cells(s.record_id, ["finding"]), cells(s.record_id, ["gap", "limitation"]),
    cells(s.record_id, ["direction"]), cells(s.record_id, ["context"]),
  ])));
  save("opportunity-matrix.svg", tableSvg("Opportunity matrix — feasibility is Hypatia's assessment", caption, [
    { label: "Opportunity", width: 125 }, { label: "Gap / status", width: 290 },
    { label: "Effort", width: 110 }, { label: "Unknowns", width: 325 },
    { label: "Author-proposal evidence", width: 250 },
  ], evidence.opportunities.map(o => [
    o.id, `${o.gap_id}: ${evidence.gaps.find(g => g.id === o.gap_id)!.status}`, o.feasibility.effort,
    o.feasibility.unknowns.join("; ") || "None recorded", o.direction_claim_ids.join(", "),
  ])));
  save("gap-directions.svg", tableSvg("Literature gaps → author-proposed directions", caption, [
    { label: "Gap / source claims", width: 475 }, { label: "Link", width: 70 },
    { label: "Author direction / source claims", width: 555 },
  ], evidence.opportunities.map(o => {
    const gap = evidence.gaps.find(g => g.id === o.gap_id)!;
    return [`${gap.id}: ${gap.statement} [${gap.claim_ids.join(", ")}] (${gap.status})`, "→",
      `${o.id}: ${opportunityText(evidence, o)} [${o.direction_claim_ids.join(", ")}]`];
  })));
  save("review-flow.svg", svg("Callimachus review flow", caption, [
    `${snapshot.ledger.queries.length} recorded query audit entries → ${snapshot.ledger.records.length} deduplicated publications → ${snapshot.handoff.included_ids.length} final included publications.`,
    `Deferred: ${snapshot.ledger.records.filter(r => r.status === "deferred").length}.`,
    `Included with full text: ${snapshot.handoff.sources.filter(s => s.kind === "fulltext").length}; abstract-only: ${snapshot.handoff.sources.filter(s => s.kind === "abstract").length}.`,
    "All final included sources have human curation dispositions. Access limitations are retained.",
  ]));
  save("evidence.json", json(evidence));
  save("context.json", json(context));
  for (const name of ["references.bib", "references.csv"]) save(name, readFileSync(inside(snapshot.directory, name)));
  save("provenance.json", json({ handoff: snapshot.handoff, evidence_digest: digest }));
  loadSnapshot(snapshot.root, snapshot.handoff.revision);
  if (digest !== evidenceDigest(snapshot)) throw new Error("Evidence changed during rendering");
  renameSync(staging, directory);
  atomicWrite(inside(root, "delivery.json"), json({ digest, directory }));
  return directory;
}
