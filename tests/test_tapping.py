"""Taps every spot, checks the celebration shows, screenshots projector mode.

    python tests/test_tapping.py
"""
from playwright.sync_api import sync_playwright
from _util import INDEX, OUT, launch, collect_errors, real_errors

with sync_playwright() as p:
    browser = launch(p)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = collect_errors(page)
    page.goto(INDEX + "?source=demo")
    page.wait_for_function("S.A !== null && S.spots.length > 0")
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "heart-hug.png"))

    pts = page.evaluate("""() => { const G=geom(), rc=cv.getBoundingClientRect();
        return S.spots.map(s => { const [x,y]=G.w2c(s.x,s.y); return [rc.left+x*rc.width/cv.width, rc.top+y*rc.height/cv.height]; }); }""")
    for x, y in pts:
        page.mouse.click(x, y)
    page.wait_for_timeout(600)
    placed = page.evaluate("S.placed.size")
    shown = page.is_visible("#celebrate")
    print(f"tapped {len(pts)} spots, {placed} checked off, celebration shown: {shown}")
    page.screenshot(path=str(OUT / "celebrate.png"))

    page.click("#again")
    page.click("#modeSeg button[data-v=projector]")
    page.wait_for_timeout(200)
    page.screenshot(path=str(OUT / "projector.png"))
    print(real_errors(errors))
    browser.close()
    assert placed == len(pts) and shown and not real_errors(errors)
