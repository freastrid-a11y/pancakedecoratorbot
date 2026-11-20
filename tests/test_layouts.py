"""Every demo pancake x every layout. Prints what was detected and planned.

    python tests/test_layouts.py
"""
from playwright.sync_api import sync_playwright
from _util import INDEX, OUT, launch, collect_errors, real_errors

DEMOS = ["heart", "smiley", "star", "letter", "spiral", "pink"]
STYLES = ["hug", "turns", "sprinkle"]

with sync_playwright() as p:
    browser = launch(p)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = collect_errors(page)
    page.goto(INDEX + "?source=demo")
    page.wait_for_function("S.A !== null")
    problems = []
    for d in DEMOS:
        for st in STYLES:
            r = page.evaluate(f"""() => {{ loadDemo('{d}'); S.style='{st}'; markSeg(); runPlan();
                return {{found:S.A.found, syrup:Math.round(S.A.syrupFrac*100), spots:S.spots.length,
                         short:S.short.map(s=>s.t.id+' '+s.got+'/'+s.want)}}; }}""")
            print(f"{d:8} {st:9} pancake={'yes' if r['found'] else 'NO '} syrup={r['syrup']:3}%  spots={r['spots']:3}  short={r['short']}")
            if not r["found"] or r["syrup"] == 0 or r["spots"] == 0:
                problems.append((d, st, r))
        page.wait_for_timeout(100)
        page.screenshot(path=str(OUT / f"layout-{d}.png"))
    print("PROBLEMS:", problems)
    print("ERRORS:", real_errors(errors))
    browser.close()
    assert not problems and not real_errors(errors)
