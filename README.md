# Pancake Topping Guide

The display software for our pancake decorator robot. The robot draws a design in chocolate syrup (or any flat sauce). An overhead camera photographs the pancake. This screen then shows the user where to put the other toppings around the syrup.

The goal is the **IKEA effect**: the robot does the hard part, and the user gets a small finishing job they can't fail at, which makes the pancake feel like theirs.

![Heart pancake with the guide circles](screenshots/heart-hug.png)

## Running it

It's one self-contained file, `index.html`, with no build step and no install.

- Double-click `index.html` to open it in Chrome, Edge, Firefox or Safari.
- Or serve the folder: `python3 -m http.server 8000`, then open http://localhost:8000

It loads a Google Font (Fredoka) if you're online. Offline, it falls back to the system font and still works.

## Using it

| Panel | What it does |
|---|---|
| **Pancake photo** | Six demo pancakes (heart, smiley, star, letter, spiral, pink sauce). You can also upload a top-down photo or drag one onto the pancake. |
| **What the camera found** | Whether it found the pancake and syrup, how much of the pancake is syrup, and a warning if a topping doesn't fit. |
| **Toppings** | Turn toppings on or off and set how many of each. |
| **Layout** | *Hug the syrup* puts each topping in its own ring around the syrup. *Take turns* alternates toppings on one ring. *Sprinkle* scatters them, filling spots closest to the syrup first. *Shuffle* gives a new random arrangement, and *Surprise me* picks a random layout with 1–2 toppings. |
| **Screen** | *Photo + guides* is for a screen next to the robot. *Projector* shows only the circles on black, for shining onto the pancake. *Show what the camera detected* highlights the syrup in pink and the pancake edge in green. |
| **Tuning** | Pancake diameter (sets real-world size), gap from syrup, and the syrup detection threshold. |
| **Export** | JSON of every spot in millimetres from the pancake center, for the robot team. |

Kids tap a circle once that topping is on it. When every circle is checked off, the celebration screen appears (or they can press **I'm done!**).

## How it works

All of the code is in the `<script>` at the bottom of `index.html`, in sections:

1. **Find the pancake** (`analyze`): The photo is shrunk to about 260 px wide for speed. Golden-brown pixels are kept (hue 12–55°, saturation ≥ 0.22, brightness ≥ 0.40), then a circle is fitted to them. The center is their average position and the radius is the 97th-percentile distance, refined 3 times.
2. **Find the syrup**: The program takes the median pancake color. Any pixel inside the circle whose color differs from it by more than the **threshold** counts as syrup. Because it compares colors instead of looking for "dark brown", it works for any sauce color. Small specks are then removed: one erode and dilate pass, then any blobs smaller than 0.2% of the pancake are dropped.
3. **Distance map** (`chamfer`): For every pixel, the program measures how far it is to the nearest syrup.
4. **Plan spots** (`plan`):
   - Pixel size is converted to millimetres with the pancake diameter, so each topping gets its real size (blueberry 12 mm, strawberry slice 24 mm, and so on).
   - Every spot must keep the **gap** from the syrup, 3 mm from the pancake edge, and 2 mm from other toppings.
   - Ring layouts collect the pixels at exactly the right distance from the syrup, chain them into a path, and space toppings evenly along it.
   - Anything that doesn't fit on a ring falls back to sprinkle.
5. **Draw** (`draw`): The program renders the photo (or black, in projector mode), the detection overlay and the pulsing guide circles at about 60 fps.

Layouts use a seeded random number generator (`mulberry32`), so the same seed always gives the same layout.

### Adding a topping

Add a line to the `TOPPINGS` list near the top of the script:

```js
{id:'raspberry', name:'Raspberries', emoji:'🍇', color:'#c2185b', mm:15, count:6, max:12},
```

`mm` is the real diameter. It decides both the circle size and how close toppings can be to each other.

## Tests

The tests drive the page in a headless browser with [Playwright](https://playwright.dev/python/).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium

python tests/test_layouts.py   # every demo × every layout; prints what was detected and planned
python tests/test_tapping.py   # taps every spot, checks the celebration shows, screenshots projector mode
```

Screenshots are saved to `test-output/` (ignored by git). Both tests print `ERRORS: []` / `[]` when there are no JavaScript errors. A font-loading error is normal if you're offline.

## Known limitations / next steps

- **Only tested on drawn demo pancakes so far.** Real photos will need the threshold tuned. Dark cooking spots can be mistaken for syrup, and shiny glare on syrup can be missed. Use the detection view while tuning.
- **No live camera in the browser preview.** On the robot (for example a Raspberry Pi), replace the upload with a camera read. In a normal browser, `navigator.mediaDevices.getUserMedia` works.
- The camera is assumed to be roughly straight overhead. A tilted camera would need perspective correction.
- Ideas: check placements with the camera (the ILC loop from our notes), sound effects, and a bigger touch-only "kid mode" for a small screen.
