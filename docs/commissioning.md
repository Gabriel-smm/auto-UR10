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

Two safety planes were defined from taught plane features. Joint position limits were then set and tested at low speed.

The key finding was that on a CB3 the safety planes restrict only the TCP. The elbow, wrists and tool body can still cross a plane as long as the TCP does not. Joint position limits were therefore needed to protect the rest of the arm, not just as a backup to the planes.

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

## 8. Result

The arm and the gripper are now controlled from one Python script: the arm over Ethernet with RTDE, the gripper over RS-485 through the adapter and wiring that were already in the cart. No parts were bought.

Several things that looked necessary along the way turned out not to be:

- reflashing the controller;
- updating PolyScope;
- the Robotiq parts order;
- ForgeOS;
- the Robotiq URCap, for computer-driven control.

## 9. Lessons

- **Test read-only first.** Read the state before sending any command, both for the robot and for the gripper.
- **Status LEDs are a free diagnostic.** The gripper LED turning blue confirmed communication before any software did.
- **When a default-settings test fails, suspect physical contact before exotic settings.** The scans of addresses and baud rates were testing a bad connection.
- **Identify connectors before ordering parts.** Photos and measurements would have ruled out the parts order straight away.
- **Trust the pendant over notes.** The robot's real address was on the pendant, not in the notes.
- **Check mechanical stack-up and cable reach early,** not just the signal path. A working signal is of no use if the parts do not fit together or the cable does not reach.
