"""appstable: docs/apps.md, the app table, generated from docs/apps.json.

Each row is one app: its toolkit, the family that glasses it, the route, how
far it was tested and the result. ``tested`` is one of:

  here     headless verify on an isolated install (bg alpha at the content
           level, text 255, popups opaque); the numbers are in ``measured``,
           filled from the verify JSON by ``--collect``
  earlier  verified in an earlier step (README, the family's doc or commit)
  probe    the research probe (B5b, content level 0.80), not this family
  no       documented only

``result`` is glass, partial or opaque; partial and opaque rows carry a
``reason``.

    python3 -m appglass.appstable --collect <verify dir>   # refresh measured
    python3 -m appglass.appstable --write                  # docs/apps.md
"""

import argparse
import json
import os
import sys

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
TESTED = ("here", "earlier", "probe", "no")
RESULTS = ("glass", "partial", "opaque")
BG_TOL = 4
MIN_SHARE = 0.6
MIN_POPUP = 0.5


def verdict(rep):
    """PASS or FAIL for one verify JSON (vrun): bg alpha mode at the level on most of the
    window, light text at 255, the popup (when one was opened) opaque."""
    w = rep.get("window") or {}
    level = rep.get("level") or 153
    pop = rep.get("popup")
    out = {"bg": w.get("alpha_mode"), "share": w.get("share_at_level"),
           "text": w.get("light_text_px_255"), "popup": pop.get("share_255") if pop else None}
    why = []
    if rep.get("error"):
        why.append("run error")
    if out["bg"] is None or abs(out["bg"] - level) > BG_TOL:
        why.append("bg %s, not %d" % (out["bg"], level))
    elif (out["share"] or 0) < MIN_SHARE:
        why.append("bg %d on %d%% only" % (out["bg"], round(100 * (out["share"] or 0))))
    if not out["text"]:
        why.append("no text at 255")
    if pop is not None and (out["popup"] or 0) < MIN_POPUP:
        why.append("popup not opaque")
    out["result"] = "FAIL" if why else "PASS"
    if why:
        out["why"] = "; ".join(why)
    return out


def load(path=None):
    with open(path or os.path.join(DOCS, "apps.json")) as f:
        return json.load(f)["apps"]


def collect(rows, verify_dir):
    """Fill ``measured`` from <verify_dir>/<basename of evidence> for the rows tested here."""
    for r in rows:
        if r.get("tested") == "here" and r.get("evidence"):
            p = os.path.join(verify_dir, os.path.basename(r["evidence"].split()[0]))
            with open(p) as f:
                r["measured"] = verdict(json.load(f))
    return rows


def _measured(m):
    if m["result"] != "PASS":
        return "FAIL: " + m.get("why", "")
    pop = "no popup" if m.get("popup") is None else "popup 255 (%d%%)" % round(100 * m["popup"])
    return "PASS: bg %d (%d%%), text 255, %s" % (m["bg"], round(100 * m["share"]), pop)


def _cell(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def _check(r):
    name = r.get("app", "?")
    if r.get("tested") not in TESTED:
        raise ValueError("%s: tested must be one of %s" % (name, TESTED))
    if r.get("result") not in RESULTS:
        raise ValueError("%s: result must be one of %s" % (name, RESULTS))
    if r["result"] != "glass" and not r.get("reason"):
        raise ValueError("%s: a %s row needs a reason" % (name, r["result"]))
    if r["tested"] == "here" and not r.get("measured"):
        raise ValueError("%s: tested here but nothing measured (--collect)" % name)


def render(rows):
    for r in rows:
        _check(r)
    n = {t: sum(1 for r in rows if r["tested"] == t) for t in TESTED}
    g = {t: sum(1 for r in rows if r["result"] == t) for t in RESULTS}
    out = [
        "# App table",
        "",
        "Generated from `docs/apps.json` by `python3 -m appglass.appstable --write`; do not edit by hand.",
        "",
        "Tested: **here** = headless verify of the family on an isolated install (content level 0.60 = 153:",
        "bg alpha at the level, light text at 255, an opened popup at 255); **earlier** = verified in an",
        "earlier step (README, the family's doc or commit); **probe** = the B5b research probe at level 0.80",
        "(204), not this family; **no** = documented only.",
        "",
        "%d apps: %d tested here, %d earlier, %d probe, %d documented. %d glass, %d partial, %d opaque." % (
            len(rows), n["here"], n["earlier"], n["probe"], n["no"], g["glass"], g["partial"], g["opaque"]),
        "",
        "| App | Toolkit | Family | Route | Tested | Result | Measured / reason | Evidence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        notes = []
        if r.get("measured"):
            notes.append(_measured(r["measured"]))
        if r.get("reason"):
            notes.append(r["reason"])
        out.append("| %s |" % " | ".join(_cell(x) for x in (
            r["app"], r.get("toolkit"), r.get("family") or "-", r.get("route"), r["tested"],
            r["result"], ". ".join(notes), r.get("evidence") or "-")))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="appglass.appstable")
    ap.add_argument("--json", default=os.path.join(DOCS, "apps.json"))
    ap.add_argument("--collect", metavar="VERIFY_DIR")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    with open(a.json) as f:
        doc = json.load(f)
    if a.collect:
        collect(doc["apps"], a.collect)
        with open(a.json, "w") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
            f.write("\n")
    md = render(doc["apps"])
    if a.write:
        with open(os.path.join(os.path.dirname(a.json), "apps.md"), "w") as f:
            f.write(md)
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
