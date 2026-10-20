#!/usr/bin/env bash
# Start URSim, Universal Robots' offline simulator (CB3, PolyScope 3.15.8),
# as a UR10 in Docker.
#
# The image is pinned by digest. It simulates a UR5 unless ROBOT_MODEL=UR10
# is set. The ports are published on localhost only. The programs folder
# ~/ursim/programs (created if missing) is mounted at /ursim/programs: copy
# installations into it from backups/, never back from it to the robot.
#
# Usage (from the repository root):
#     scripts/ursim.sh              # runs in the foreground
#     docker stop ursim_cb3         # from another terminal; --rm removes the container
#
# GUI: http://localhost:6080/vnc.html?host=localhost&port=6080
# Press ON, then START, then run the scripts with --sim (127.0.0.1).

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAGE=universalrobots/ursim_cb3@sha256:ecdab8a2ec1ec795466214f66596b162ae6d21cdc77c3a5c550cf40d753932a4
NAME=ursim_cb3
MODEL=UR10
PROGRAMS="$HOME/ursim/programs"

# 5900 VNC, 6080 VNC in a browser, 29999 Dashboard Server,
# 30001-30004 script interfaces and RTDE (ur_rtde)
PORTS=(5900 6080 29999 30001-30004)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

mkdir -p "$PROGRAMS"

publish=()
for p in "${PORTS[@]}"; do
    publish+=(-p "127.0.0.1:$p:$p")
done

exec docker run --rm -it --name "$NAME" \
    -e ROBOT_MODEL="$MODEL" \
    "${publish[@]}" \
    -v "$PROGRAMS:/ursim/programs" \
    "$IMAGE"
