# Testing the camera setup

This is a step-by-step plan for checking that the camera works, starting with no hardware at all and ending with real pancakes under the robot. Each stage only needs what the stages before it needed, plus one new thing, so if something breaks you know which piece to look at.

| Stage | What you need | Time |
|---|---|---|
| [1. Automated tests](#1-automated-tests) | A laptop | 5 min |
| [2. The server on a laptop, no camera](#2-the-server-on-a-laptop-no-camera) | A laptop | 10 min |
| [3. A laptop webcam](#3-a-laptop-webcam) | A laptop with a webcam, a pancake photo or a real pancake | 10 min |
| [4. The Pi and its camera](#4-the-pi-and-its-camera) | The Pi, its camera, a second device on the same Wi-Fi | 30 min |
| [5. Real pancakes](#5-real-pancakes) | The full robot, pancakes, syrup, toppings | 1 hour |

Write down what you find as you go. There's a [results sheet](#results-sheet) at the end to copy into an issue or a message to the team.

---

## 1. Automated tests

These check that nothing is broken before you test anything by hand.

```bash
git clone https://github.com/freastrid-a11y/pancakedecoratorbot.git
cd pancakedecoratorbot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
```

Then run each test from the project folder:

```bash
python tests/test_camera_server.py
```

```bash
python tests/test_layouts.py
```

```bash
python tests/test_tapping.py
```

```bash
python tests/test_camera_ui.py
```

- [ ] `test_camera_server.py` ends with `ALL PASSED`
- [ ] `test_layouts.py` ends with `PROBLEMS: []` and `ERRORS: []`
- [ ] `test_tapping.py` ends with `[]`
- [ ] `test_camera_ui.py` ends with `ALL PASSED`

Screenshots land in `test-output/`. Open `camera-pi-auto.png` to see what a good result looks like.

If a test fails, stop here and share its output. The later stages will fail for the same reason.

---

## 2. The server on a laptop, no camera

This checks the whole Pi workflow on a laptop, using a sample photo in place of the camera.

**Start the server** (in its own terminal window, and leave it running):

```bash
python3 pi/camera_server.py --camera file
```

It should print `file camera ready`.

**Open the display** at http://localhost:8000.

- [ ] The **Raspberry Pi** tab is selected by itself, and it says *Connected to file camera* (the page remembers the last tab you used, so if you've picked another tab before, click **Raspberry Pi**)
- [ ] The pancake area shows the sample pancake with a red **● LIVE** label
- [ ] **📸 Take photo** replaces the live view with topping circles, and *What the camera found* says *Pancake found* and *Syrup found*

**Pretend to be the robot.** Press **👁 Live view** first, then in a second terminal:

```bash
python3 pi/robot_client.py
```

- [ ] Within about a second, the live view is replaced by the topping circles, and the message says *The robot finished the syrup, so I took the photo*
- [ ] Untick *Take the photo when the robot says the syrup is done*, press **Live view**, and run `robot_client.py` again. This time nothing should happen.

**Try the API directly**, which is what the robot team will use:

- [ ] http://localhost:8000/api/status shows `"camera_ok": true` and a `syrup_done` count
- [ ] http://localhost:8000/api/snapshot.jpg shows the sample photo

**Check the error messages:**

- [ ] Stop the server (Ctrl+C). Within a few seconds of pressing **Connect**, the display says it *can't reach the camera server*, and **Take photo** is greyed out.
- [ ] Start the server again and press **Connect**. It connects again.

---

## 3. A laptop webcam

This checks that the syrup detection works on a real camera image, not only on the drawn demos. Keep the server from stage 2 running, or start it again.

Open http://localhost:8000 and pick the **This computer** tab. (It must be `localhost` or the `index.html` file itself. Browsers block cameras on other `http://` addresses.)

- [ ] **👁 Live view** asks for camera permission, then shows the webcam over the pancake area
- [ ] If the laptop has more than one camera, they're all in the drop-down after permission is granted
- [ ] **📸 Take photo** freezes the frame and places topping circles

Point the camera at something pancake-shaped, as straight down as you can, filling most of the frame:

1. A pancake photo on a phone or tablet screen, or printed out (easiest)
2. A real pancake with syrup on a plate (best)

Then turn on **Show what the camera detected** (under *Screen*). Pink should cover the syrup and nothing else, and the green circle should sit on the pancake edge.

- [ ] Pancake found
- [ ] Syrup found, with roughly the right amount of pink
- [ ] Note the **Syrup detection threshold** (under *Tuning*) that worked best: ____

If you block the camera permission, the tab should say how to allow it again instead of failing silently.

---

## 4. The Pi and its camera

### 4a. Check the camera on its own

Before involving our code, make sure the Pi can see the camera.

**Pi Camera Module:**

```bash
rpicam-hello --list-cameras
```

(On older Raspberry Pi OS versions the command is `libcamera-hello --list-cameras`.) It should list one camera. If it says *No cameras available*, check the ribbon cable direction and that it's fully seated, then reboot.

**USB webcam:**

```bash
ls /dev/video*
```

Plug the webcam in and run it again. A new `/dev/videoN` should appear. Then install OpenCV:

```bash
sudo apt install -y python3-opencv
```

- [ ] Camera type: ☐ Pi Camera Module ☐ USB webcam (model: ____)
- [ ] The Pi sees the camera

### 4b. Start the server

```bash
git clone https://github.com/freastrid-a11y/pancakedecoratorbot.git
cd pancakedecoratorbot
python3 pi/camera_server.py
```

It picks the Pi Camera Module if there is one, otherwise USB webcam 0. To force one, add `--camera pi` or `--camera usb` (and `--device 1` for a second USB camera).

- [ ] It prints `... camera ready`, not `NOT working`

If it says `NOT working`, the reason is on the same line. `ModuleNotFoundError: cv2` means OpenCV isn't installed (step 4a). `can't open camera` usually means the wrong `--device` number, or another program already has the camera open.

### 4c. Open the display from another device

On a laptop, tablet or phone on the **same Wi-Fi**, open http://raspberrypi.local:8000. If that doesn't load, use the Pi's IP address instead (run `hostname -I` on the Pi to find it), e.g. http://192.168.1.42:8000.

- [ ] The page loads and connects by itself, naming the right camera type
- [ ] The live view is smooth enough to line up a pancake (about 10 frames a second)
- [ ] **Take photo** works and the photo is sharp and well lit

Also try opening the page on the Pi's own screen, if it has one.

### 4d. The robot's signal

On the Pi, while the display shows the live view:

```bash
python3 pi/robot_client.py
```

- [ ] The display takes the photo within about a second
- [ ] With two displays open at once (say, a laptop and a tablet), both take the photo

### 4e. Starting on boot (optional)

Follow the instructions at the top of `pi/pancake-camera.service`, then reboot the Pi.

- [ ] After the reboot, http://raspberrypi.local:8000 works without logging in to the Pi

### 4f. When things go wrong

- [ ] Unplug the USB webcam (or stop the server) while the display is open. The display should say the live view stopped, and `/api/status` should show `camera_ok: false` with a reason.

  Known limitation: after plugging the webcam back in, **restart the server**. It doesn't reopen the camera by itself yet.

---

## 5. Real pancakes

This is the test that matters: does a real pancake from the robot get sensible topping circles?

**Set up the camera:**

1. Mount the camera straight above where the pancake will be. A tilted camera makes the circle fit and the sizes wrong (the app doesn't correct for tilt yet).
2. Use the live view to center the pancake, so it fills about two-thirds of the frame with some plate or table around it.
3. Use even light from above or the sides. Avoid a lamp that makes a bright reflection on the syrup.
4. Measure the pancake's diameter with a ruler and set **Pancake diameter** under *Tuning*.

**For each pancake:**

1. Have the robot draw the syrup, and send `syrup_done()` (or press **Take photo**).
2. Turn on **Show what the camera detected** and check the pink and green outlines.
3. Adjust the **Syrup detection threshold** until the pink matches the syrup. Write down the value.
4. Put real toppings on the circles. Do they fit, and do they stay off the syrup?
5. If you have kids (or adults) to test on, watch whether they understand what to do without help.

Try to cover:

- [ ] A pale pancake and a well-browned one (dark cooking spots are the most likely thing to be mistaken for syrup)
- [ ] Each syrup design you plan to use
- [ ] Chocolate syrup and at least one other sauce color, if you plan to use others
- [ ] The room lighting you'll actually use, e.g. daytime and evening

**Check sizes:** use **Export for the robot team** to get the JSON, and measure one or two spots on the real pancake with a ruler. `x_mm` and `y_mm` are measured from the pancake center, with +x to the right and +y down in the camera image. They should be within a few millimetres.

---

## Troubleshooting

| What you see | Likely cause | What to try |
|---|---|---|
| `raspberrypi.local` doesn't load | The device can't resolve `.local` names (common on Android and some Windows setups) | Use the Pi's IP address from `hostname -I` |
| *Can't reach the camera server* | Server not running, wrong address, or different Wi-Fi network | Check the server's terminal; check both devices are on the same network |
| *Connected, but the camera isn't working* | Camera not detected, or in use by another program | Stage 4a; close other camera programs; restart the server |
| **This computer** tab: *only on a secure page* | The page was opened from `http://<pi-address>`, which browsers don't trust for cameras | Use `http://localhost` or open `index.html` directly |
| Pink covers brown spots on the pancake | Threshold too low | Raise the **Syrup detection threshold** |
| Parts of the syrup aren't pink | Threshold too high, or a bright reflection on the syrup | Lower the threshold; soften or move the light |
| *Couldn't find a golden pancake* | Pancake very pale or very dark, or a colored plate or table | Better light; a plain plate; tell the team, since the color range may need widening |
| Circles are the wrong size | **Pancake diameter** setting is wrong, or the camera is tilted | Measure and set the diameter; straighten the camera |

---

## Results sheet

Copy this into a GitHub issue or a message to the team.

```
Date:
Tester:
Camera: Pi Camera Module / USB webcam (model: )
Pi model and OS version:

Stage 1, automated tests:        pass / fail (paste output if fail)
Stage 2, server without camera:  pass / fail
Stage 3, laptop webcam:          pass / fail   best threshold:
Stage 4, Pi and camera:          pass / fail
Stage 5, real pancakes:
  pancakes tried:
  syrup designs and colors:
  best threshold:              pancake diameter:
  detection problems seen:
  did toppings fit the circles?
  did testers understand what to do?

Anything else:
```
