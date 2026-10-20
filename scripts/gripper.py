"""Minimal Modbus RTU driver for the Robotiq 2F-85 gripper.

The gripper is reached through the FTDI USB-to-RS-485 adapter inside the
TaskMate cart base. Settings are the Robotiq defaults: slave address 9,
115200 baud, 8N1.

Command line:
    python gripper.py status     # read status (default)
    python gripper.py activate   # required after every power cycle
    python gripper.py open
    python gripper.py close

As a module:
    import gripper as g
    s = g.connect()
    g.write(s, g.ACT_GOTO, pos=255, speed=64, force=0)
    print(g.status(s))
"""

import glob
import sys
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BAUD = 115200
ADDR = 9            # Modbus slave address
TIMEOUT = 0.3       # serial read timeout (s)


def _find_port():
    """Prefer the stable /dev/serial/by-id name; fall back to ttyUSB0."""
    matches = glob.glob('/dev/serial/by-id/*RS-485*')
    return matches[0] if matches else '/dev/ttyUSB0'


PORT = _find_port()

# Action request byte (rACT register)
ACT_RESET = 0x00    # clear activation
ACT_ACTIVATE = 0x01  # rACT
ACT_GOTO = 0x09     # rACT + rGTO: move to requested position

# Positions (0 = fully open, 255 = fully closed)
POS_OPEN = 0
POS_CLOSED = 255

# Status values
STA_ACTIVATED = 3   # gSTA: activation complete
OBJ_MOVING = 0      # gOBJ: still moving toward requested position

# ---------------------------------------------------------------------------
# Modbus helpers
# ---------------------------------------------------------------------------


def crc(data):
    """Modbus CRC-16, returned little-endian as 2 bytes."""
    c = 0xFFFF
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c.to_bytes(2, 'little')


def frame(body):
    """Prefix the slave address and append the CRC."""
    msg = bytes([ADDR]) + body
    return msg + crc(msg)


# ---------------------------------------------------------------------------
# Gripper commands
# ---------------------------------------------------------------------------


def connect(port=PORT):
    """Open the serial link to the gripper."""
    import serial
    return serial.Serial(port, BAUD, timeout=TIMEOUT)


def write(s, action, pos=0, speed=0, force=0):
    """Write the three output registers starting at 0x03E8 (function 0x10)."""
    s.reset_input_buffer()
    s.write(frame(bytes([0x10, 0x03, 0xE8, 0x00, 0x03, 0x06,
                         action, 0x00, 0x00, pos, speed, force])))
    return s.read(8)


def status(s):
    """Read the input registers at 0x07D0. Returns a dict, or None on no reply."""
    s.reset_input_buffer()
    s.write(frame(bytes([0x03, 0x07, 0xD0, 0x00, 0x03])))
    r = s.read(11)
    if len(r) != 11 or r[-2:] != crc(r[:-2]):
        return None
    b = r[3]
    return {
        'act': b & 1,              # gACT
        'goto': (b >> 3) & 1,      # gGTO
        'sta': (b >> 4) & 3,       # gSTA
        'obj': (b >> 6) & 3,       # gOBJ
        'fault': r[5],
        'pos': r[7],
        'current': r[8],
    }


def wait(s, test, secs):
    """Poll status until test(status) is true or secs elapse. Returns last status."""
    start = time.time()
    st = None
    while time.time() - start < secs:
        st = status(s)
        if st and test(st):
            break
        time.sleep(0.1)
    return st


def activate(s, secs=15):
    """Reset then activate. The fingers open and close fully: keep clear."""
    write(s, ACT_RESET)
    time.sleep(0.5)
    write(s, ACT_ACTIVATE)
    return wait(s, lambda st: st['sta'] == STA_ACTIVATED, secs)


def move(s, pos, speed=64, force=100, secs=8):
    """Move to pos (0-255) and wait until the motion ends or an object is hit."""
    write(s, ACT_GOTO, pos, speed, force)
    time.sleep(0.2)
    return wait(s, lambda st: st['obj'] != OBJ_MOVING, secs)


def open_(s, **kw):
    return move(s, POS_OPEN, **kw)


def close(s, **kw):
    return move(s, POS_CLOSED, **kw)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    commands = {
        'status': status,
        'activate': activate,
        'open': open_,
        'close': close,
    }
    if cmd not in commands:
        raise SystemExit(f'Usage: python gripper.py [{"|".join(commands)}]')

    s = connect()
    try:
        print(commands[cmd](s))
    finally:
        s.close()


if __name__ == '__main__':
    main()
