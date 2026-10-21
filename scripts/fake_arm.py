"""In-memory stand-in for the RTDE control and receive interfaces.

For offline tests and for `run_task.py --sim --backend fake`: the same calls
the skills make on RTDEControlInterface and RTDEReceiveInterface, with no
robot and no URSim. Moves end instantly (or after move_time seconds), the
kinematics keep every joint well inside its limits, and the active TCP is the one safety.py expects, so safety.preflight
runs its plane checks exactly as against the robot.

Joint angles encode the pose: q = Q + K * pose, so the fake inverse and
forward kinematics are exact inverses of each other and every q stays within
a few degrees of Q, far from the joint limits.

As a module:
    import fake_arm
    receive = fake_arm.FakeReceive(start_pose)
    control = fake_arm.FakeControl(receive)
"""

import time

import safety

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Joint angles (rad) returned by the fake inverse kinematics: shoulder at -90 deg,
# far from every limit in safety.JOINT_MIN / JOINT_MAX.
Q = [0.0, -1.5708, 1.5708, -1.5708, -1.5708, 0.0]
K = 0.01                # rad per unit of pose


def ik(pose):
    return [a + K * p for a, p in zip(Q, pose)]


def fk(q):
    return [(a - b) / K for a, b in zip(q, Q)]

# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


class FakeReceive:
    """RTDEReceiveInterface stand-in: holds the TCP pose the fake control moves."""

    def __init__(self, pose):
        self.pose = list(pose)

    def getActualTCPPose(self):
        return list(self.pose)

    def getActualQ(self):
        return ik(self.pose)

    def disconnect(self):
        pass


class FakeControl:
    """RTDEControlInterface stand-in. move_time > 0 makes each move take that long."""

    def __init__(self, receive, move_time=0.0):
        self.receive = receive
        self.move_time = move_time
        self.moves = []         # every moveL / moveJ target pose, in order
        self.stops = 0          # stopL / stopJ calls
        self._target = None
        self._end = 0.0

    def getTCPOffset(self):
        return list(safety.ACTIVE_TCP)

    def getInverseKinematics(self, pose, qnear=None):
        return ik(pose)

    def getForwardKinematics(self, q, tcp_offset=None):
        return fk(q)

    def isPoseWithinSafetyLimits(self, pose):
        return True

    def moveL(self, pose, speed=0.25, accel=1.2, asynchronous=False):
        self.moves.append(list(pose))
        self._target, self._end = list(pose), time.time() + self.move_time
        if not asynchronous:
            while self.getAsyncOperationProgress() >= 0:
                time.sleep(0.001)
        return True

    def moveJ(self, q, speed=1.05, accel=1.4, asynchronous=False):
        return self.moveL(fk(q), speed, accel, asynchronous)

    def getAsyncOperationProgress(self):
        """0 while a move runs, -1 when none is running (as ur_rtde)."""
        if self._target is None:
            return -1
        if time.time() < self._end:
            return 0
        self.receive.pose, self._target = self._target, None
        return -1

    def stopL(self, decel=10.0):
        """Stop where the arm is: the pose stays at the start of the move."""
        self.stops += 1
        self._target = None
        return True

    def stopJ(self, decel=2.0):
        return self.stopL(decel)

    def stopScript(self):
        self._target = None
