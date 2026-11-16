"""Score results/ -> results/report.md

Per vendor, per category: WER (after normalize.py on both sides), English-term recall, latency
medians, error count, long-take survival. Then the worst clips per vendor, reference vs hypothesis,
because averages hide everything.
"""
import utf8  # noqa: F401  must come before anything prints
import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

import jiwer

from normalize import normalize, latin_tokens

RESULTS = Path("results")
TRANSLIT = Path("translit.json")   # optional: {"panadol": ["بانادول","بندول"], ...}


def med(xs):
    xs = [x for x in xs if x is not None]
    return f"{st.median(xs):.2f}" if xs else "–"


def term_hits(terms, hyp_raw, translit):
    """How many of the sentence's English terms came out — Latin, or an accepted Arabic spelling."""
    if not terms:
        return None
    lat = set(latin_tokens(hyp_raw))
    hyp_n = normalize(hyp_raw)
    hit = 0
    for t in terms:
        tl = t.lower()
        if tl in lat or any(alt and normalize(alt) in hyp_n for alt in translit.get(tl, [])):
            hit += 1
    return hit, len(terms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worst", type=int, default=8)
    a = ap.parse_args()

    translit = json.loads(TRANSLIT.read_text(encoding="utf-8")) if TRANSLIT.exists() else {}
    translit = {k.lower(): v for k, v in translit.items()}

    rows = []
    for f in RESULTS.glob("*/*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if not r.get("ref"):
            continue
        ref_n, hyp_n = normalize(r["ref"]), normalize(r.get("text") or "")
        r["wer"] = jiwer.wer(ref_n, hyp_n) if ref_n else None
        r["cer"] = jiwer.cer(ref_n, hyp_n) if ref_n else None
        r["terms"] = term_hits(r.get("english_terms") or [], r.get("text") or "", translit)
        r["len_ratio"] = (len(hyp_n.split()) / len(ref_n.split())) if ref_n else None
        rows.append(r)
    if not rows:
        print("no results yet — run run_ab.py first")
        return

    by = defaultdict(list)
    for r in rows:
        by[(r["vendor"], r["category"])].append(r)
    vendors = sorted({r["vendor"] for r in rows})
    cats = sorted({r["category"] for r in rows}, key=lambda c: (c != "dialect", c != "codeswitch", c))

    out = ["# STT A/B report", ""]
    out += [f"clips: {len({r['case_id'] for r in rows})}   results: {len(rows)}   vendors: {', '.join(vendors)}", ""]

    out += ["## WER by category (lower is better)", "", "| vendor | " + " | ".join(cats) + " | all |", "|---|" + "---|" * (len(cats) + 1)]
    for v in vendors:
        cells = []
        for c in cats:
            xs = [r["wer"] for r in by.get((v, c), []) if r["wer"] is not None]
            cells.append(f"{st.mean(xs):.3f}" if xs else "–")
        allx = [r["wer"] for r in rows if r["vendor"] == v and r["wer"] is not None]
        out.append(f"| {v} | " + " | ".join(cells) + f" | {st.mean(allx):.3f} |")
    out.append("")

    out += ["## English-term recall (higher is better)", "", "| vendor | terms seen | recalled | recall |", "|---|---|---|---|"]
    for v in vendors:
        hit = tot = 0
        for r in rows:
            if r["vendor"] == v and r["terms"]:
                hit += r["terms"][0]; tot += r["terms"][1]
        out.append(f"| {v} | {tot} | {hit} | {(hit / tot):.2f} |" if tot else f"| {v} | 0 | – | – |")
    out.append("")

    out += ["## Latency and reliability", "", "| vendor | median first partial (s) | median final lag (s) | errors | runs |", "|---|---|---|---|---|"]
    for v in vendors:
        vr = [r for r in rows if r["vendor"] == v]
        out.append(f"| {v} | {med([r['first_partial_s'] for r in vr])} | {med([r['final_lag_s'] for r in vr])} | "
                   f"{sum(1 for r in vr if r.get('error'))} | {len(vr)} |")
    out.append("")

    longs = [r for r in rows if r["category"] == "long"]
    if longs:
        out += ["## Long take", "", "| vendor | audio (s) | error | words out / words ref |", "|---|---|---|---|"]
        for r in sorted(longs, key=lambda r: r["vendor"]):
            out.append(f"| {r['vendor']} | {r['audio_s']} | {r.get('error') or '–'} | {r['len_ratio']:.2f} |")
        out.append("")

    reps = defaultdict(list)
    for r in rows:
        reps[(r["vendor"], r["case_id"])].append(r["wer"])
    var = defaultdict(list)
    for (v, _), xs in reps.items():
        xs = [x for x in xs if x is not None]
        if len(xs) > 1:
            var[v].append(st.pstdev(xs))
    if var:
        out += ["## Run-to-run variance (std of WER across repeats, same clip)", ""]
        out += [f"- {v}: {st.mean(xs):.3f}" for v, xs in sorted(var.items())]
        out.append("")

    out += [f"## Worst {a.worst} clips per vendor", ""]
    for v in vendors:
        vr = sorted([r for r in rows if r["vendor"] == v and r["wer"] is not None], key=lambda r: -r["wer"])[:a.worst]
        out += [f"### {v}", "", "| clip | WER | reference | hypothesis |", "|---|---|---|---|"]
        for r in vr:
            out.append(f"| {r['case_id']} | {r['wer']:.2f} | {r['ref']} | {(r.get('text') or '').strip() or ('ERR ' + str(r.get('error'))[:60])} |")
        out.append("")

    RESULTS.joinpath("report.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:len(out) - 1][:40]))
    print(f"\n-> {RESULTS / 'report.md'}")


if __name__ == "__main__":
    main()
