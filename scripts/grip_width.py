"""Block width <-> 2F-85 finger position, from calibration points.

When the gripper stops on a block (gOBJ 2), its pos (0-255 counts) depends
on the block width. The relation is not linear over the stroke: a straight
line from 85 mm at pos 3 to 0 mm at pos 228 puts 73 mm at pos 35, but the
gripper stopped at 67. Widths between the points are interpolated.

Used by fake_bench.py (width -> pos) and by skills.py (pos -> width_mm in
skill results). Add a point to CALIBRATION for each real block measured.

As a module:
    from grip_width import pos_for, width_for
    pos_for(73)      # 67
    width_for(67)    # 73.0
"""

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STROKE_MM = 85.0        # 2F-85 opening

# (width mm, pos) points, in increasing width and decreasing pos
CALIBRATION = [
    (0.0, 228),         # assumed: closed on nothing (the observed no-object stop)
    (73.0, 67),         # measured 2026-10-20: 73 mm object, force 0 and 100
    (STROKE_MM, 3),     # assumed: fully open (the observed open stop)
]

# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def _interpolate(x, points):
    """Piecewise-linear y at x over (x, y) points sorted by x; clamped at the ends."""
    x = max(points[0][0], min(points[-1][0], x))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)


def pos_for(width_mm):
    """Finger position (counts) when stopped on a block of this width."""
    return round(_interpolate(width_mm, CALIBRATION))


def width_for(pos):
    """Block width (mm) for a finger position where the gripper stopped on an object."""
    return round(_interpolate(pos, sorted((p, w) for w, p in CALIBRATION)), 1)
