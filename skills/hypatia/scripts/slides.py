"""Minimal Beamer presentation of the validated review and assessment."""

import re


TEX_ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&",
    "#": r"\#", "%": r"\%", "_": r"\_", "^": r"\textasciicircum{}", "~": r"\textasciitilde{}",
}


def slide_text(value: str) -> str:
    return re.sub(r"\s+", " ", "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in value)).strip()


def tex(value: str) -> str:
    return "".join(TEX_ESCAPES.get(c, c) for c in slide_text(value))


def slide_list(items, empty, budget=850, limit=3):
    selected: list[str] = []
    for item in map(slide_text, items):
        if len(selected) >= limit or len(item) > budget or any(len(word) > 70 for word in item.split(" ")):
            continue
        selected.append(item)
        budget -= len(item)
    omitted = len(items) - len(selected)
    if not items:
        selected.append(empty)
    if omitted:
        selected.append(f"{omitted} item(s) omitted for space; see report.md for the complete assessment.")
    return "\n".join([r"\begin{itemize}", *(r"\item " + tex(item) for item in selected), r"\end{itemize}"])


def shortlist(evidence):
    gaps = {g["id"]: g for g in evidence["gaps"]}
    return [
        o for o in evidence["opportunities"]
        if o["feasibility"]["effort"] == "low"
        and gaps[o["gap_id"]]["status"] in ("open-in-reviewed-corpus", "partly-addressed")
    ]


def opportunity_text(evidence, opportunity):
    claims = {c["id"]: c for c in evidence["claims"]}
    return "; ".join(claims[claim_id]["statement"] for claim_id in opportunity["direction_claim_ids"])


def frame(title, body):
    return rf"\begin{{frame}}[t,shrink=0]{{{tex(title)}}}" + "\n\\small\n" + body + "\n\\end{frame}"


def beamer(snapshot, evidence, context):
    handoff, ledger = snapshot["handoff"], snapshot["ledger"]
    claims = {c["id"]: c for c in evidence["claims"]}
    sources = {s["record_id"]: s for s in handoff["sources"]}
    gaps = {g["id"]: g for g in evidence["gaps"]}

    def citations(ids):
        result = []
        for claim_id in ids:
            claim = claims[claim_id]
            source = sources[claim["source_id"]]
            locator = "abstract" if source["kind"] == "abstract" else f"PDF p. {claim['page']}"
            result.append(f"{claim_id}: {claim['source_id']}, {locator} ({claim['verification']['status']})")
        return "; ".join(result)

    fulltext = sum(s["kind"] == "fulltext" for s in handoff["sources"])
    unresolved = [c for c in evidence["claims"] if c["verification"]["status"] != "supported"]
    limitations = [
        f"{s['record_id']}: " + "; ".join(filter(None, [s["limitation"], *s["warnings"]]))
        for s in handoff["sources"] if s["limitation"] or s["warnings"]
    ] + [
        f"{r['source_id']}: unreadable. {r['note']}"
        for r in evidence["source_reviews"] if r["status"] == "unreadable"
    ] + [f"{citations([c['id']])}: {c['verification']['reason']}" for c in unresolved]
    findings = [
        f"{f['id']}: {f['statement']} Evidence: {citations(f['claim_ids'])}. Strength: {f['strength']} "
        f"Counterevidence: {citations(f['disagreements']) if f['disagreements'] else 'none recorded; this does not establish consensus'}."
        for f in evidence["findings"]
    ]
    gap_items = [
        f"{g['id']}: {g['statement']} Status: {g['status']}. Evidence: {citations(g['claim_ids'])}. "
        f"Currency: {g['currency']['rationale']} ({len(g['currency']['checked_source_ids'])}/{len(handoff['included_ids'])} publications checked). "
        f"Subsequent evidence: {citations(g['currency']['claim_ids']) if g['currency']['claim_ids'] else 'none recorded'}."
        for g in evidence["gaps"]
    ]
    opportunities = []
    for opportunity in evidence["opportunities"]:
        feasibility = opportunity["feasibility"]
        opportunities.append(
            f"{opportunity['id']}: {opportunity_text(evidence, opportunity)} Evidence: {citations(opportunity['direction_claim_ids'])}. "
            f"Gap: {opportunity['gap_id']} ({gaps[opportunity['gap_id']]['status']}). "
            f"Effort: {feasibility['effort']}; {feasibility['rationale']} "
            f"Prerequisites: {'; '.join(feasibility['prerequisites']) or 'unknown'}. "
            f"Unknowns: {'; '.join(feasibility['unknowns']) or 'none recorded'}. "
            f"Resources: {', '.join(feasibility['resource_ids']) or 'none supplied'}."
        )
    return "\n\n".join([
        "% Compile with: lualatex -no-shell-escape -interaction=nonstopmode -halt-on-error slides.tex",
        r"\documentclass[aspectratio=169]{beamer}",
        r"\usepackage{fontspec}", r"\setsansfont{DejaVu Sans}", r"\tracinglostchars=3",
        r"\setbeamertemplate{navigation symbols}{}",
        r"\setbeamertemplate{footline}{\hfill\insertframenumber\kern1em\vskip2pt}",
        r"\begin{document}",
        frame("Callimachus / Hypatia summary", "\n".join([
            slide_list([f"Question: {ledger['question']}", f"Audience: {context['audience']}"], "", 400, 2),
            "\\medskip\n" + tex(f"Search cutoff: {handoff['cutoff']}. Final included publications: {len(handoff['included_ids'])}.") + r"\par",
            tex(f"Callimachus revision: {handoff['revision']}") + r"\par",
            "\\medskip\nPublication counts are not independent-study counts or evidence-quality scores.\\par",
            "\\medskip\nSelected whole entries are shown in review order. Full criteria, assessments, exact quotations and references: \\texttt{report.md}.",
        ])),
        frame("Callimachus criteria", "\n".join([
            tex(f"Approved criteria version: {ledger['criteria']['version']}") + r"\par",
            "\\medskip\n\\textbf{Include}",
            slide_list(ledger["criteria"]["include"], "No inclusion criteria specified.", 250, 3),
            "\\medskip\n\\textbf{Exclude}",
            slide_list(ledger["criteria"]["exclude"], "No exclusion criteria specified.", 250, 3),
        ])),
        frame("Hypatia: findings and disagreements", slide_list(findings, "No supported findings were established.", 850, 2)),
        frame("Hypatia: gaps in the reviewed corpus", "\n".join([
            slide_list(gap_items, "No author-stated gaps were established.", 750, 2),
            "\\medskip\nOpen means open within this corpus and its cutoff; incomplete coverage remains unresolved.",
        ])),
        frame("Hypatia: author proposals and feasibility", "\n".join([
            tex(f"{len(shortlist(evidence))} direction(s) meet the low-effort criteria.") + r"\par",
            "Feasibility is Hypatia's assessment, not an author claim.\\par",
            slide_list(opportunities, "No author-proposed opportunities were established.", 750, 2),
        ])),
        frame("Coverage, limitations and researcher constraints", "\n".join([
            tex(f"{len(ledger['queries'])} query audit entries; {len(ledger['records'])} deduplicated publications.") + r"\par",
            tex(f"Included: {fulltext} full text; {len(handoff['sources']) - fulltext} abstract only. "
                f"{len(unresolved)} uncertain or contradicted claim(s); {sum(r['status'] == 'unreadable' for r in evidence['source_reviews'])} unreadable source(s).") + r"\par",
            "\\medskip\n\\textbf{Access and uncertainty}",
            slide_list(limitations, "No access warnings or unresolved claims recorded; this does not establish certainty.", 250, 2),
            "\\medskip\n\\textbf{Researcher resources}",
            slide_list([f"{r['id']}: {r['description']}" for r in context["resources"]],
                       "No resources supplied; low-effort shortlisting is disabled.", 200, 2),
            "\\medskip\nHypatia performs no additional search. All details and omitted entries remain in \\texttt{report.md}.",
        ])),
        r"\end{document}", "",
    ])
