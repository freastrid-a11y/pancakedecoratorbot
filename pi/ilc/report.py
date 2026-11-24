"""A before/after report page for a simulator run (test-output/ilc/report-<control>.html).

For each design: the first and last pancake photo, the width error for every pancake,
and the line width along the path before and after learning, against the target.
Plain HTML with inline SVG charts; no libraries.
"""
import html
import os

BEFORE, AFTER, TARGET = "#d9822b", "#2b6cb0", "#2f8f5b"


def _fmt(v):
    return f"{v:.2f}"


def error_chart(rows, w=420, h=170):
    """Width error (mm) for every pancake."""
    pad_l, pad_r, pad_t, pad_b = 40, 12, 12, 30
    n = len(rows)
    ys = [r["true_rms"] for r in rows]
    top = max(0.5, max(ys) * 1.15)
    X = lambda i: pad_l + (w - pad_l - pad_r) * (i / max(1, n - 1))
    Y = lambda v: pad_t + (h - pad_t - pad_b) * (1 - v / top)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Width error per pancake">']
    for t in _ticks(top):
        out.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>'
                   f'<text x="{pad_l - 6}" y="{Y(t) + 4:.1f}" class="ax" text-anchor="end">{t:g}</text>')
    for i in range(n):
        if n <= 12 or i in (0, n - 1) or (i + 1) % 5 == 0:
            out.append(f'<text x="{X(i):.1f}" y="{h - 10}" class="ax" text-anchor="middle">{i + 1}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{AFTER}" stroke-width="2.5" stroke-linejoin="round"/>')
    for i, v in enumerate(ys):
        c = BEFORE if i == 0 else AFTER
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{c}"><title>pancake {i + 1}: {_fmt(v)} mm</title></circle>')
    out.append('</svg>')
    return "".join(out)


def width_chart(profiles, targets, spacing=2.0, w=420, h=190):
    """Measured width along the path (strokes one after another), pancake 1 vs last."""
    pad_l, pad_r, pad_t, pad_b = 40, 12, 12, 30
    gap = 6.0                                           # mm between strokes on the x axis
    lengths = [len(st[0]) for st in profiles[0]]
    total = sum((n - 1) * spacing for n in lengths) + gap * (len(lengths) - 1)
    top = max(10.0, max(targets) * 2)
    X = lambda mm: pad_l + (w - pad_l - pad_r) * (mm / max(total, 1e-9))
    Y = lambda v: pad_t + (h - pad_t - pad_b) * (1 - min(v, top) / top)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Line width along the path">']
    for t in _ticks(top):
        out.append(f'<line x1="{pad_l}" x2="{w - pad_r}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>'
                   f'<text x="{pad_l - 6}" y="{Y(t) + 4:.1f}" class="ax" text-anchor="end">{t:g}</text>')
    x0 = 0.0
    for si, n in enumerate(lengths):
        x1 = x0 + (n - 1) * spacing
        t = targets[si]
        out.append(f'<rect x="{X(x0):.1f}" y="{Y(t + 1):.1f}" width="{X(x1) - X(x0):.1f}" '
                   f'height="{Y(t - 1) - Y(t + 1):.1f}" fill="{TARGET}" opacity=".12"/>'
                   f'<line x1="{X(x0):.1f}" x2="{X(x1):.1f}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" '
                   f'stroke="{TARGET}" stroke-dasharray="4 3" stroke-width="1.5"/>')
        for prof, color in ((profiles[0], BEFORE), (profiles[-1], AFTER)):
            widths, valid = prof[si]
            seg = []
            for i, (v, ok) in enumerate(zip(widths, valid)):
                if ok:
                    seg.append(f"{X(x0 + i * spacing):.1f},{Y(v):.1f}")
                elif seg:
                    out.append(_line(seg, color)); seg = []
            if seg:
                out.append(_line(seg, color))
        x0 = x1 + gap
    out.append('</svg>')
    return "".join(out)


def _line(seg, color):
    return f'<polyline points="{" ".join(seg)}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/>'


def _ticks(top):
    step = 0.25 if top <= 1 else 0.5 if top <= 2.5 else 1 if top <= 5 else 2 if top <= 12 else 5
    return [round(i * step, 2) for i in range(int(top / step) + 1)]


def write_report(out, reports, control, learn, pancakes):
    tag = f"{control}{'' if learn else '-noilc'}"
    title = f"ILC simulator: learning {control}" if learn else f"ILC simulator: baseline, no learning"
    cards = []
    for r in reports:
        a, b = r["rows"][0], r["rows"][-1]
        change = (b["true_rms"] - a["true_rms"]) / a["true_rms"] * 100
        name = html.escape(r["design"])
        cards.append(f"""
<section class="card">
  <h2>{name}</h2>
  <div class="kpis">
    <div><span>Width error</span><b>{_fmt(a['true_rms'])} → {_fmt(b['true_rms'])} mm</b><em class="{'good' if change < -10 else ''}">{change:+.0f}%</em></div>
    <div><span>Within ±1 mm</span><b>{a['within_1mm'] * 100:.0f}% → {b['within_1mm'] * 100:.0f}%</b></div>
    <div><span>End blobs</span><b>{a['blob_mm3']:.0f} → {b['blob_mm3']:.0f} mm³</b></div>
  </div>
  <div class="photos">
    <figure><img src="{name}-{r['tag']}-first.png" alt="{name}, pancake 1"><figcaption><i style="background:{BEFORE}"></i>Pancake 1 · {_fmt(a['true_rms'])} mm</figcaption></figure>
    <figure><img src="{name}-{r['tag']}-last.png" alt="{name}, pancake {pancakes}"><figcaption><i style="background:{AFTER}"></i>Pancake {pancakes} · {_fmt(b['true_rms'])} mm</figcaption></figure>
  </div>
  <div class="charts">
    <figure><figcaption>Width error (mm) for each pancake, 1 to {pancakes}</figcaption>{error_chart(r['rows'])}</figure>
    <figure><figcaption>Line width (mm) along the path; gaps are points that can't be measured. <i style="background:{BEFORE}"></i>pancake 1 <i style="background:{AFTER}"></i>pancake {pancakes} <i style="background:{TARGET}"></i>target ±1 mm</figcaption>{width_chart(r['profiles'], r['targets'])}</figure>
  </div>
</section>""")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ILC Simulator Report</title>
<style>
  :root{{--bg:#fbf6ee;--card:#fffdf9;--ink:#2b2118;--muted:#7a6a58;--line:#eadfcd;--good:#2f8f5b}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
  main{{max-width:1000px;margin:0 auto;padding:24px 16px 48px}}
  h1{{font-size:24px;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 20px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin-bottom:18px}}
  h2{{margin:0 0 10px;font-size:19px}}
  .kpis{{display:flex;flex-wrap:wrap;gap:10px 28px;margin-bottom:12px}}
  .kpis span{{display:block;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
  .kpis b{{font-size:17px;font-variant-numeric:tabular-nums}} .kpis em{{font-style:normal;margin-left:6px;color:var(--muted);font-weight:600}}
  .kpis em.good{{color:var(--good)}}
  .photos,.charts{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  @media (max-width:700px){{.photos,.charts{{grid-template-columns:1fr}}}}
  figure{{margin:0}} img{{width:100%;border-radius:10px;display:block}}
  figcaption{{font-size:13px;color:var(--muted);margin:6px 0}}
  figcaption i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 8px;vertical-align:-1px}}
  figcaption i:first-child{{margin-left:0}}
  .chart{{width:100%;height:auto;display:block}} .grid{{stroke:var(--line)}} .ax{{font-size:10px;fill:var(--muted)}}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p class="sub">{pancakes} simulated pancakes per design. Width error is the RMS difference from the target width over the points that can be measured (the simulator knows the true width). Photos: detected syrup outlined in pink, the planned path in cyan.</p>
{"".join(cards)}
</main></body></html>"""
    path = os.path.join(out, f"report-{tag}.html")
    with open(path, "w") as f:
        f.write(page)
    return path
