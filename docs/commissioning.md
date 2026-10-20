# Commissioning a second-hand UR10 cell

This write-up covers how a donated UR10 cell with no documentation was brought back into service and put under Python control. It keeps the wrong turns as well as the answers, because the wrong turns are where most of the time went and where the next person to inherit a cell like this can save the most. For the day-to-day procedure, see [setup.md](setup.md).

## 1. Starting point

The lab was given a Universal Robots UR10 with a CB3 controller, mounted on a Ready Robotics TaskMate R10 cart. It arrived with no documentation, and nobody in the lab had worked with it before. The cart came with Ready Robotics' ForgeOS control layer and the TeachMate handheld device. Ready Robotics shut down in 2024, so ForgeOS was unsupported.

Several grippers came with the donation: a Robotiq 2F-85, a Gimatic pneumatic gripper, Schunk pneumatic 2- and 3-finger grippers, and a Magswitch magnetic gripper. The Robotiq 2F-85 was chosen as the main gripper.

## 2. First power-on and choosing a control path

The arm was powered on and moved by hand with Freedrive and by jogging from the pendant. Before any programmed motion, a risk assessment was written for the cell.

ForgeOS did not get far: it stayed stuck asking whether the robot was on. Rather than build on software that nobody supports any more, we moved the cell to native PolyScope, with Python control over RTDE planned on top. This kept the UR controller in charge of real-time control and safety, and left the higher-level logic in code we could read and change.

## 3. Safety configuration

The safety settings had been locked by the previous owner, and access was recovered.

Safety planes were defined from taught plane features. Joint position limits were then set and tested at low speed.

The key finding was that on a CB3 the safety planes restrict only the TCP. The elbow, wrists and tool body can still cross a plane as long as the TCP does not. Joint position limits were therefore needed to protect the rest of the arm, not just as a backup to the planes.

Our notes said there were two planes. When the installation was later exported to a USB stick and read on a computer, it showed three: `backwall`, `leftwall` and `Base`, a plane below the robot base. It also showed that only the shoulder joint is narrowed, to at most −51°, and only in Normal mode. The TCP (`rough_robotiq`, 165.8 mm) and the payload (1.8 kg) were then set for the 2F-85. The planes still check the 162.8 mm TCP that was active when they were defined.

The installation file stores each plane as a normal and a distance, with no explicit "allowed side". Working through the taught feature points showed two things. First, the stored normal is the opposite of the feature's +Z, which points into the prohibited zone, so the stored normal points to the allowed side. Second, the stored distance already includes the displacement, which places each limit 10–90 mm beyond the taught points. These values now live in [`safety.py`](../scripts/safety.py), and the full table is in [setup.md](setup.md#safety-configuration).

The software margins from `safety.py watch` and the pose readout from `show_pose.py` were later confirmed against the pendant: the margins match where the robot stops at a plane, and the pose matches the **Move** tab.

## 4. The fieldbus error

With the safety configuration in place, programs failed with `C207A0 Fieldbus input disconnected`. The cause was EtherNet/IP and PROFINET, left enabled by the ForgeOS setup, waiting for a master that no longer existed. Disabling both in the Installation tab and saving a new installation cleared the error.

The same change turned out to be required for RTDE. A fieldbus adapter claims RTDE input registers, so with the leftover settings in place the Python control interface could not connect.

## 5. The gripper: a wrong diagnosis, then the missing link

The first attempt was to drive the 2F-85 through the robot's digital I/O. That cannot work: the 2F-85 is controlled over RS-485 using Modbus RTU, not through digital I/O. The pneumatic tubes and I/O wires running through the cart belong to the pneumatic grippers, which are switched through solenoid valves.

The CB3 wrist connector carries only digital and analog I/O and power. It has no RS-485 lines, so the gripper could not simply be plugged into the wrist.

This is where the main wrong turn happened. Working from an 8-pin plug on the gripper cable, we first concluded that two Robotiq parts had to be ordered, and then three. A closer look showed that the gripper plug was larger than the wrist connector and that both were male. The plug had never been meant for the wrist. The lesson was to identify connectors from photos and measurements before ordering anything.

The gripper plug did fit port A of the TeachMate, and the TeachMate's cable ran into the cart base. That suggested a hypothesis: ForgeOS had talked to the gripper through ordinary wiring in the cart, and that wiring could be reused without ForgeOS.

## 6. Proving it

A USB cable from the cart's internal ForgeOS PC was unplugged and connected to the control computer instead. It showed up as an FTDI "USB TO RS-485" adapter (`0403:6015`). The converter we thought we had to buy was already inside the cart.

The gripper plug had bent pins, which were straightened. Even so, the first status reads got no reply. Scans across addresses, baud rates and parity settings returned only garbled bytes, starting with `0x10`, from a second device on the line, probably the TeachMate electronics. Eventually a recognisable gripper reply appeared and the gripper LED turned blue.

From then on, clean reads worked at the Robotiq defaults: address 9, 115200 baud, 8N1. The settings had been the defaults all along. The earlier silence was most likely poor contact in the repaired plug, and the scans had only been testing a bad connection under different settings. With a reliable link, activate, open and close all worked from Python, using a small driver that builds the Modbus frames directly ([`gripper.py`](../scripts/gripper.py)).

## 7. Network and first Python motion

The first ping to the robot failed for two separate reasons. First, the computer's wired interface had no IPv4 address, so the ping went out over Wi-Fi. Second, once that was fixed, the robot turned out to be at `192.168.0.1`, not the address in earlier notes. The lesson: read the address off the pendant, and change the computer's settings to match rather than the robot's.

The first `ur_rtde` test was read-only: connect the receive interface and read the robot state, with no motion commands. After that, [`pick_test.py`](../scripts/pick_test.py) ran the first combined sequence: open the gripper, lift the TCP 2 cm, close, open, and return to the start pose. The TCP came back within about 0.1 mm of where it started.

## 8. Simulation

To try scripts without moving the arm, URSim, Universal Robots' offline simulator, was set up on the control laptop in Docker ([`ursim.sh`](../scripts/ursim.sh)). The CB3 image is pinned by digest. The robot's exported installation was loaded into it and showed the same safety checksum (`313597321`), TCP and payload, so the simulator enforces the same safety configuration as the robot.

Three things needed care:

- **The image simulates a UR5 by default.** It has to be started with `ROBOT_MODEL=UR10`, or poses, reach and the distances to the safety planes do not match the robot.
- **Docker needs the `docker` group.** Without it, every command fails with `permission denied` on `/var/run/docker.sock`. Adding the user to the group and logging in again fixes it.
- **The simulator is newer than the robot.** The image reports PolyScope 3.15.8; the robot runs 3.15.6. Files therefore go one way only, robot to simulator: nothing the simulator saves goes back to the robot, and the robot is not updated to match.

URSim simulates the arm and controller only. The gripper, objects and the camera are not part of it. For the gripper, [`fake_gripper.py`](../scripts/fake_gripper.py) stands in for the Modbus driver, with the same functions and status fields, and close results set by a scenario; its block positions are placeholders until the real blocks are made and measured. Whether its stops and the motion scripts behave exactly as on the robot is still to be checked (see [setup.md](setup.md#simulation-ursim)).

For the blocks, [`fake_bench.py`](../scripts/fake_bench.py) keeps a bench in memory: slots at the taught poses in [`slots.json`](../scripts/slots.json), blocks with widths, and a bin. It turns a close or open at the TCP position into the gripper reading the real cell would give, so that pick-and-place logic which knows the blocks only through the gripper can run without the robot. Faults (slip, miss, width noise, ghost block) are injected from a seeded generator and logged, so a failing run can be repeated. Two of its first assumptions were wrong when checked on the gripper:

- **At force 0, a dropped object does not show in the status.** The bench first modelled a slip as the status turning to gOBJ 3. On the real 2F-85, closed with force 0 on a 73 mm object (gOBJ 2, pos 67, current 0), the object was pulled out and the status stayed gOBJ 2, pos 67. With no holding current the gripper cannot sense the loss. The same test at force 100 gave current 5 while holding, and when the object was pulled out the fingers closed fully and the status turned to gOBJ 3, pos 228, with the same stop position (67) as at force 0. The bench now chooses from the force of the close: silent at force 0, a status change with force. Gripping with force is what makes a dropped block detectable; `gripper.py` still closes at force 0 by default.
- **Width is not linear in pos.** A straight line over the 85 mm stroke gave pos 35 for 73 mm; the gripper stopped at 67. The bench now interpolates in a calibration table that holds the measured point, and more points are to be added as blocks are measured.

## 9. Result

The arm and the gripper are now controlled from one Python script: the arm over Ethernet with RTDE, the gripper over RS-485 through the adapter and wiring that were already in the cart. No parts were bought.

Several things that looked necessary along the way turned out not to be:

- reflashing the controller;
- updating PolyScope;
- the Robotiq parts order;
- ForgeOS;
- the Robotiq URCap, for computer-driven control.

## 10. Lessons

- **Test read-only first.** Read the state before sending any command, both for the robot and for the gripper.
- **Status LEDs are a free diagnostic.** The gripper LED turning blue confirmed communication before any software did.
- **When a default-settings test fails, suspect physical contact before exotic settings.** The scans of addresses and baud rates were testing a bad connection.
- **Identify connectors before ordering parts.** Photos and measurements would have ruled out the parts order straight away.
- **Trust the pendant over notes.** The robot's real address was on the pendant, not in the notes.
- **Read safety limits from an exported installation, not from memory.** The notes said two safety planes; the installation had three.
- **Check mechanical stack-up and cable reach early,** not just the signal path. A working signal is of no use if the parts do not fit together or the cable does not reach.
- **Make the simulator match the robot, not the other way round.** Set the model, load the robot's own installation and check its checksum. Never let files saved by a newer PolyScope flow back to the robot.
