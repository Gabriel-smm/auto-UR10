# Prompts for the README images

The images in this folder are made with Claude Design from these prompts, so they can be regenerated when the project changes. For each image, paste the [common style](#common-style) followed by that image's prompt, then export a PNG with the file name given.

| File | Size | Shown in the README under |
|---|---|---|
| `readme-banner.png` | 1600 × 400 | top of the page |
| `readme-system-overview.png` | 1600 × 900 | The cell |
| `readme-decision-loop.png` | 1600 × 900 | How it decides |
| `readme-safety-layers.png` | 1600 × 900 | How it stays safe |
| `readme-sim-to-real.png` | 1600 × 900 | Try it without a robot |

## Common style

```text
Create one static image for the README of a robotics software project on GitHub. It is one
of a set of five that must look like one family. Single artboard, no pages, no animation,
nothing interactive.

Audience: someone technical who has never seen this project and will look at the image for
ten seconds.

Style
- Flat, calm technical illustration, like a well-drawn engineering notebook. Not a slide
  and not a marketing page. No gradients, drop shadows, glow, 3D or photorealism.
- Solid background #F7F5EF on the whole artboard, not transparent, with square corners. It
  has to read well on both GitHub's light and dark themes.
- Ink #1E2A38 for text and outlines. Muted ink #5B6673 for secondary text.
- Teal #1F7A7A for real hardware. Orange #D9591F only for safety. Grey #8A94A0, dashed, for
  anything simulated or planned. Use no other colours.
- Rounded rectangles with 2 px outlines and no fill or a very light tint of their colour.
  Simple line icons where they help. Arrows are 2 to 3 px with small solid heads.
- Inter or a similar clean sans-serif. A monospace font only for file names and commands.
- The image is shown at about half its size on GitHub, so no text under 28 px on the
  1600 px artboard, and titles in boxes at 36 px or more. Keep generous empty space.

Strict rules
- Use exactly the text given below, and no other words: no extra title, caption, numbers,
  claims or footnotes.
- No logos or brand marks of Universal Robots, Robotiq, Intel or anyone else. Draw generic
  devices.
- Do not add components or connections that are not described.
```

## `readme-banner.png`

```text
Size: 1600 × 400 px. A simple visual identity for the project, not a diagram.

Left third: a simple geometric mark of a six-axis robot arm, built from a few thick rounded
line segments and circles for the joints, in teal #1F7A7A, ending in a small two-finger
gripper above one small square block in ink #1E2A38. It should be abstract, like a logo mark,
not a depiction of a real product, with no background scene.

Right two thirds, left-aligned and vertically centred:
- "auto-UR10", very large, in ink, semi-bold.
- Below it, in muted ink: "A second-hand UR10, controlled from Python"
```

## `readme-system-overview.png`

```text
Size: 1600 × 900 px. Shows how one computer reaches the parts of a robot cell. Read from left
to right, with two parallel horizontal paths and a third, dashed one below them.

Left, vertically centred: one large box with a laptop icon, ink outline.
  Title: "Control computer"
  Secondary: "Python scripts"

Upper path, in teal, going right from the computer:
  Arrow labelled "Ethernet · RTDE"
  Box "UR10 controller", secondary text "Real-time control and safety limits"
  Short arrow
  Box "UR10 arm", with a small generic robot arm icon

Middle path, in teal, going right from the computer:
  Arrow labelled "USB → RS-485 · Modbus RTU"
  Box "TeachMate"
  Short arrow
  Box "Robotiq 2F-85 gripper", with a generic two-finger gripper icon, directly below the
  "UR10 arm" box

Between the "UR10 arm" and "Robotiq 2F-85 gripper" boxes: a short vertical line with no
arrowheads, labelled "Mounted on the arm". It is a physical mounting, not a data link. The arm
and the gripper are driven over separate links.

Lower path, dashed grey, from the computer:
  Dashed arrow, then a dashed grey box "RealSense D455 camera", with a generic camera icon
  and secondary text "Planned: not connected yet"
```

## `readme-decision-loop.png`

```text
Size: 1600 × 900 px. Shows a repeating cycle of six steps. Arrange six rounded boxes evenly
around a large clockwise ring, with arrows along the ring from each box to the next, and
step 6 returning to step 1. Steps 1, 2, 5 and 6 are in teal. Steps 3 and 4 are in orange,
because they are the safety steps.

Boxes, clockwise from the top left. Each has a title and one line of secondary text:
  1 "Read": "Only what the gripper and arm report"
  2 "Decide": "Rules or a model choose the next step"
  3 "Check": "Plan the path against the safety limits"
  4 "Confirm": "The operator approves each step on the real robot"
  5 "Move": "The arm or gripper does one step"
  6 "Measure": "The result feeds the next step"

Centre of the ring, large: "One step at a time"

Two small branches, outside the ring:
- From box 2 "Decide": a thin dashed arrow labelled "Not confident enough" to a small box
  "Ask the operator", and from that small box a thin dashed arrow on to box 3 "Check".
- From box 3 "Check": a thin orange arrow labelled "Fails" to a small orange box
  "Nothing moves".
```

## `readme-safety-layers.png`

```text
Size: 1600 × 900 px. Shows the layers a robot step must pass before the arm moves. Read from
top to bottom, as a vertical stack in the left two thirds of the artboard, with down arrows
between the rows.

Top row, ink outline: "A step is chosen"

Then three orange layers, full width of the stack. Each has a title and one line of secondary
text:
  "Software check": "30 mm from safety planes, 3° from joint limits"
  "Operator": "Confirms every step on the real robot"
  "UR controller": "Enforces planes and joint limits in real time"

Bottom row, teal, with a generic robot arm icon: "The arm moves"

To the right of each orange layer: a short thin arrow pointing right to a small text label
saying what that layer does to a bad step:
  Software check → "Refuses the plan"
  Operator → "Skips or aborts"
  UR controller → "Stops the arm"

Across the bottom of the artboard, in muted ink, with a small warning-triangle line icon:
"These layers do not see objects: the operator watches for blocks."
```

## `readme-sim-to-real.png`

```text
Size: 1600 × 900 px. Shows that the same scripts run against either of two targets.

Top centre: one large box, ink outline, "Same Python scripts". Two arrows go down from it to
two columns of equal size.

Left column, solid teal outline. Arrow label in monospace: "default"
  Column title: "Real robot"
  Two stacked rows, with generic icons:
    "UR10 arm and controller"
    "Robotiq 2F-85 gripper"
  Inside the column at the bottom, in monospace:
    "TARGET: REAL ROBOT (192.168.0.1)"

Right column, dashed grey outline. Arrow label in monospace: "--sim"
  Column title: "Simulator"
  Three stacked rows, with file names in monospace:
    "URSim": "Simulated arm, with the robot's safety settings"
    "fake_gripper.py": "Stand-in gripper"
    "fake_bench.py": "Simulated blocks and injected faults"
  Inside the column at the bottom, in monospace:
    "TARGET: SIMULATOR (127.0.0.1)"

The left column has only two rows, so give them more height: both columns must end at the
same level.
```
