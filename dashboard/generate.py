#!/usr/bin/env python3
"""Generate the VFB connectome import dashboard from connectomes.yaml.

Runs every probe defined in the manifest, then writes:
  dashboard/site/index.html   colour-coded matrix (published to GitHub Pages)
  dashboard/STATUS.md         emoji matrix for at-a-glance viewing in the repo

Usage:  python dashboard/generate.py
No arguments; all configuration lives in connectomes.yaml.
"""

import datetime
import html
import os

import yaml

import probes

HERE = os.path.dirname(os.path.abspath(__file__))

# fill state -> (hex colour, text colour, glyph, emoji)
STATE_STYLE = {
    "done":         ("#2e7d32", "#fff", "✓", "\U0001F7E9"),  # green  ✓ 🟩
    "needs_update": ("#ef6c00", "#fff", "↑", "\U0001F7E7"),  # orange ↑ 🟧
    "in_progress":  ("#c62828", "#fff", "…", "\U0001F7E5"),  # red    … 🟥
    "not_started":  ("#9e9e9e", "#fff", "",       "⬜"),      # grey     ⬜
    "unknown":      ("#cfcfcf", "#333", "?",       "\U0001F533"),  # hatch  ? 🔳
}
LIVE_LEGEND = "● live now   ○ done but not live yet"


def load_manifest():
    with open(os.path.join(HERE, "connectomes.yaml")) as f:
        return yaml.safe_load(f)


def build_context(meta):
    repo_root = os.path.abspath(os.path.join(HERE, ".."))
    return {
        "owl_index_url": meta.get("owl_index_url"),
        "pdb_tx_url": meta.get("pdb_tx_url"),
        "jenkins_base": meta.get("jenkins_base"),
        "repo_root": repo_root,
    }


def evaluate(manifest, ctx):
    """Return a list of connectome dicts each with a 'cells' map: stage_id -> cell."""
    stage_ids = [s["id"] for s in manifest["stages"]]
    rows = []
    for c in manifest["connectomes"]:
        cells = {}
        for sid in stage_ids:
            spec = (c.get("stages") or {}).get(sid) or {}
            state, detail = probes.run_fill(spec.get("fill"), ctx, c, sid)
            if state == "done" and spec.get("update"):
                needs, udet = probes.run_update(spec["update"], ctx, c)
                if needs:
                    state, detail = "needs_update", udet
            live, ldet = probes.run_live(spec.get("live"), ctx, c, sid)
            cells[sid] = {
                "state": state,
                "detail": detail + (("  |  " + ldet) if ldet else ""),
                "live": live,
            }
        rows.append({"c": c, "cells": cells})
    return rows, stage_ids


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
CSS = """
:root{color-scheme:light dark}
body{font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;margin:24px;background:#fafafa;color:#1a1a1a}
@media(prefers-color-scheme:dark){body{background:#161616;color:#eee}}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#777;margin:0 0 16px;font-size:12px}
table{border-collapse:separate;border-spacing:3px}
th{font-weight:600;font-size:12px;text-align:left;padding:4px 8px;vertical-align:bottom}
th.stage{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;height:120px}
td.name{font-weight:600;white-space:nowrap;padding-right:8px}
td.name a{color:inherit;text-decoration:none;border-bottom:1px dotted #999}
td.meta{color:#777;font-size:12px;white-space:nowrap;padding:0 8px}
td.cell{width:34px;height:34px;text-align:center;border-radius:6px;position:relative;
        color:#fff;font-size:15px;cursor:default}
.dot{position:absolute;top:3px;right:4px;font-size:10px;line-height:1}
.legend{margin:18px 0;font-size:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}
.legend .sw{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:5px}
.controls{margin:12px 0}
.hidden{display:none}
"""

JS = """
function onlyAttention(cb){
  document.querySelectorAll('tr.row').forEach(function(tr){
    var flag = tr.dataset.attention === '1';
    tr.classList.toggle('hidden', cb.checked && !flag);
  });
}
"""


def _cell_html(cell):
    colour, text, glyph, _ = STATE_STYLE.get(cell["state"], STATE_STYLE["unknown"])
    dot = ""
    if cell["live"] is True:
        dot = '<span class="dot">●</span>'
    elif cell["live"] is False and cell["state"] in ("done", "needs_update"):
        dot = '<span class="dot">○</span>'
    tip = html.escape("%s — %s" % (cell["state"], cell["detail"]), quote=True)
    return ('<td class="cell" style="background:%s;color:%s" title="%s">%s%s</td>'
            % (colour, text, tip, glyph, dot))


def render_html(manifest, rows, stage_ids, when):
    meta = manifest.get("meta", {})
    repo = meta.get("github_repo", "")
    labels = {s["id"]: s["label"] for s in manifest["stages"]}

    head = ["<th></th>", "<th>Version</th>"]
    head += ['<th class="stage">%s</th>' % html.escape(labels[s]) for s in stage_ids]
    head += ["<th>Owner</th>"]

    body = []
    for r in rows:
        c = r["c"]
        attention = any(
            r["cells"][s]["state"] in ("needs_update", "in_progress", "unknown")
            or (r["cells"][s]["state"] == "done" and r["cells"][s]["live"] is False)
            for s in stage_ids
        )
        name = html.escape(c.get("label", c["id"]))
        if c.get("runner") and repo:
            name = '<a href="https://github.com/%s/blob/main/%s">%s</a>' % (
                repo, c["runner"], name)
        issue = ""
        if c.get("issue") and repo:
            issue = ' <a href="https://github.com/%s/issues/%s">#%s</a>' % (
                repo, c["issue"], c["issue"])
        cells = "".join(_cell_html(r["cells"][s]) for s in stage_ids)
        body.append(
            '<tr class="row" data-attention="%d">'
            '<td class="name">%s%s</td>'
            '<td class="meta">%s</td>%s<td class="meta">%s</td></tr>'
            % (1 if attention else 0, name, issue,
               html.escape(str(c.get("version") or "—")), cells,
               html.escape("@" + c["owner"] if c.get("owner") else "—")))

    legend = []
    for state, (colour, _t, _g, _e) in STATE_STYLE.items():
        legend.append('<span><span class="sw" style="background:%s"></span>%s</span>'
                      % (colour, state.replace("_", " ")))
    legend.append("<span>" + html.escape(LIVE_LEGEND) + "</span>")

    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VFB Connectome Import Status</title><style>%s</style></head><body>
<h1>VFB Connectome Import Status</h1>
<p class="sub">Auto-generated %s · fill = work state · dot = live in PDB release</p>
<div class="controls"><label><input type="checkbox" onchange="onlyAttention(this)">
Show only rows needing attention</label></div>
<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>
<div class="legend">%s</div>
<script>%s</script></body></html>""" % (
        CSS, html.escape(when), "".join(head), "".join(body),
        "".join(legend), JS)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
LEGEND_MD = ("Legend: 🟩 done · 🟧 needs update · 🟥 in progress / not live · "
             "⬜ not started · 🔳 unknown  ·  🔵 live in release · ⚪ done but not live yet")


def _matrix_lines(manifest, rows, stage_ids):
    """The legend + matrix table as markdown lines (shared by STATUS.md and README)."""
    labels = {s["id"]: s["label"] for s in manifest["stages"]}
    out = [LEGEND_MD, ""]
    header = ["Connectome", "Ver"] + [labels[s] for s in stage_ids] + ["Owner"]
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        c = r["c"]
        line = [c.get("label", c["id"]), str(c.get("version") or "—")]
        for s in stage_ids:
            cell = r["cells"][s]
            emoji = STATE_STYLE.get(cell["state"], STATE_STYLE["unknown"])[3]
            if cell["live"] is True:
                emoji += "🔵"
            elif cell["live"] is False and cell["state"] in ("done", "needs_update"):
                emoji += "⚪"
            line.append(emoji)
        line.append("@" + c["owner"] if c.get("owner") else "—")
        out.append("| " + " | ".join(line) + " |")
    return out


def render_markdown(manifest, rows, stage_ids, when):
    out = ["# Connectome Import Status", "",
           "_Auto-generated %s. Do not edit by hand — edit `connectomes.yaml`._" % when,
           ""]
    out += _matrix_lines(manifest, rows, stage_ids)
    out.append("")
    return "\n".join(out)


def pages_url(manifest):
    repo = manifest.get("meta", {}).get("github_repo", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return "https://%s.github.io/%s/" % (owner.lower(), name)
    return ""


def main():
    manifest = load_manifest()
    ctx = build_context(manifest.get("meta", {}))
    rows, stage_ids = evaluate(manifest, ctx)
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Generated output goes ONLY into site/ (published to GitHub Pages, never
    # committed to git) — so regenerating can never cause a merge conflict.
    site_dir = os.path.join(HERE, "site")
    os.makedirs(site_dir, exist_ok=True)
    with open(os.path.join(site_dir, "index.html"), "w") as f:
        f.write(render_html(manifest, rows, stage_ids, when))
    with open(os.path.join(site_dir, "STATUS.md"), "w") as f:
        f.write(render_markdown(manifest, rows, stage_ids, when))

    # console summary
    for r in rows:
        flags = [s for s in stage_ids
                 if r["cells"][s]["state"] in ("needs_update", "in_progress")]
        print("%-16s %s" % (
            r["c"].get("label", r["c"]["id"]),
            ("needs attention: " + ", ".join(flags)) if flags else "ok"))
    print("\nWrote dashboard/site/index.html and dashboard/site/STATUS.md")
    url = pages_url(manifest)
    if url:
        print("Live dashboard: " + url)


if __name__ == "__main__":
    main()
