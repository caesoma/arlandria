#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests==2.32.*",  # used transitively via _common; uv builds an isolated env
# ]
# ///
"""ledger.py - the only writer of criteria / screening / status. Schema-safe.

Every screening decision and criteria change goes through here so the ledger stays valid and the
human-decision lock is enforced in one place; nothing else hand-edits <review>/ledger.json. Each verb
loads the ledger, mutates it in memory, recomputes derived stats, saves, and prints a small JSON
result. Used across the whole workflow: criteria at the gates (steps 2/7), decide while screening
(5) and curating (9), status to shelve/un-shelve clusters (6), note to log the rationale exchanged
with the researcher at a gate (steps 2/6).

Verbs:
  criteria --ledger L --include "..." [...] --exclude "..." [...] [--question "..."]
  decide   --ledger L --id ID --stage abstract|fulltext --decision include|exclude|borderline
           --by llm|human [--relevance high|med|low] [--covers tag ...] [--reason "..."] [--summary "..."]
  status   --ledger L --status active|deferred --id ID [ID ...]
  note     --ledger L --gate criteria|triage --text "..."   (append a gate-exchange summary)

Locking (the researcher is the final curator): a `--by llm` write never overwrites a
`decided_by:human` decision. A `--by human` write always applies, stashing the LLM's prior call into
the `proposed` shadow field - so the LLM's original recommendation stays visible for audit after an
override.
"""
import argparse, json, sys
from _common import load_ledger, save_ledger, recompute_stats, now


def find(led, rid):
    return next((r for r in led["records"] if r["id"] == rid), None)  # first record with this id


def cmd_criteria(led, a):
    # replace the active criteria, bumping the version and appending the old+new to history
    v = led["criteria"].get("version", 0) + 1  # monotonic version - decisions reference the version
    inc, exc = a.include or [], a.exclude or []
    led["criteria"] = {"version": v, "include": inc, "exclude": exc,
                       "history": led["criteria"].get("history", []) +
                       [{"version": v, "at": now(), "include": inc, "exclude": exc}]}
    if a.question:  # record the original question (ledger.py is the only writer of led["question"])
        led["question"] = a.question
    return {"criteria_version": v, "question": led.get("question")}


def cmd_decide(led, a):
    r = find(led, a.id)
    if not r:
        return {"error": "record not found", "id": a.id}
    # borderline is an abstract-stage hedge; at full text it must resolve to include/exclude
    if a.stage == "fulltext" and a.decision == "borderline":
        return {"error": "borderline is abstract-stage only; resolve to include/exclude at full text"}
    blk = r["screening"][a.stage]  # the abstract or fulltext screening block to write
    # LOCK: an LLM write must not clobber a decision a human already made
    if a.by == "llm" and blk.get("decided_by") == "human" and blk["decision"] != "unscreened":
        return {"id": a.id, "stage": a.stage, "locked": True,
                "kept": blk["decision"], "note": "human decision is locked against LLM writes"}
    # human overriding the LLM: stash the LLM's call in `proposed` before overwriting
    if a.by == "human" and blk.get("decided_by") == "llm" and blk["decision"] != "unscreened":
        blk["proposed"] = {"decision": blk["decision"], "reason": blk["reason"],
                           "relevance": r["assessment"].get("relevance")}
    # write the decision, stamping who/when and which criteria version it was decided against
    blk.update(decision=a.decision, reason=a.reason, at=now(),
               criteria_version=led["criteria"].get("version"), decided_by=a.by)
    if a.relevance:
        r["assessment"]["relevance"] = a.relevance
    if a.covers:
        r["assessment"]["covers"] = a.covers  # cluster tags - reshape the report's groupings
    if a.summary:  # paper summary ("what it covers") - kept distinct from the decision reason above
        r["assessment"]["summary"] = a.summary
    recompute_stats(led)
    return {"id": a.id, "stage": a.stage, "decision": a.decision, "decided_by": a.by}


def cmd_status(led, a):
    # shelve (deferred) or un-shelve (active) records - orthogonal to their screening decision
    touched = []
    for rid in a.id:
        r = find(led, rid)
        if r:
            r["status"] = a.status
            touched.append(rid)
    recompute_stats(led)
    return {"status": a.status, "set_on": touched}


def cmd_note(led, a):
    # append a free-text summary of a gate exchange - the rationale behind a scope / triage decision.
    # Append-only and review-level (distinct from a record's per-paper `notes`); never overwritten, so
    # the human<->LLM back-and-forth that shaped the review stays recoverable on resume.
    entry = {"at": now(), "gate": a.gate,
             "criteria_version": led["criteria"].get("version"),  # the scope state this note refers to
             "text": a.text}
    led.setdefault("exchanges", []).append(entry)  # setdefault: tolerate ledgers minted before this field
    return {"note_added": True, "gate": a.gate, "n_notes": len(led["exchanges"])}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)  # one subparser per verb (criteria/decide/status/note)

    c = sub.add_parser("criteria"); c.add_argument("--ledger", required=True)
    c.add_argument("--include", nargs="*", default=[]); c.add_argument("--exclude", nargs="*", default=[])
    c.add_argument("--question", help="the original plain-English question; recorded once, on the first criteria call")

    d = sub.add_parser("decide"); d.add_argument("--ledger", required=True)
    d.add_argument("--id", required=True)
    d.add_argument("--stage", required=True, choices=["abstract", "fulltext"])
    d.add_argument("--decision", required=True, choices=["include", "exclude", "borderline"])
    d.add_argument("--by", required=True, choices=["llm", "human"])
    d.add_argument("--relevance", choices=["high", "med", "low"])
    d.add_argument("--covers", nargs="*", default=None)
    d.add_argument("--reason", help="why this decision was made (screening.<stage>.reason)")
    d.add_argument("--summary", help="what the paper covers (assessment.summary); distinct from --reason")

    s = sub.add_parser("status"); s.add_argument("--ledger", required=True)
    s.add_argument("--status", required=True, choices=["active", "deferred"])
    s.add_argument("--id", nargs="+", required=True)

    n = sub.add_parser("note"); n.add_argument("--ledger", required=True)
    n.add_argument("--gate", required=True,
                   help="which gate the summary is from: criteria (step 2) | triage (step 6)")
    n.add_argument("--text", required=True,
                   help="free-text summary of the human<->LLM exchange and the rationale for the decision")

    a = ap.parse_args()
    led = load_ledger(a.ledger)
    # dispatch to the verb's handler, then persist and report what it did
    out = {"criteria": cmd_criteria, "decide": cmd_decide, "status": cmd_status, "note": cmd_note}[a.verb](led, a)
    # skip the write on a no-op: a locked llm-vs-human decision or a record-not-found error
    # changed nothing, so don't bump `updated` for it
    if not (out.get("error") or out.get("locked")):
        save_ledger(a.ledger, led)
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
