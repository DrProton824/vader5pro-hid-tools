# Vader 5 Pro | Command Reference

Protocol reference for the Flydigi Vader 5 Pro
(`VID 0x37D7`, `PID 0x2401`).

Primary vendor interface:

- HID Interface 1 (`MI_01`)
- Usage Page `0xFFA0`
- 32-byte HID reports
- Protocol header: `5A A5`

Evidence levels:

- **Confirmed** — directly captured/tested on Vader 5 Pro hardware.
- **Established** — implemented and exercised by `padctl`; treated as reliable.
- **Observed** — directly captured, but semantics remain unknown.
- **Corroborated** — independently supported by another implementation.

---

## Command Overview

| Command | Direction | Function | Status |
|---------|-----------|----------|--------|
| `0x01` | Device → Host | Firmware / device information | **Confirmed** |
| `0xA1` | Host ↔ Device | Device information / capabilities | **Confirmed / Established** |
| `0x02` | Host ↔ Device | Status/configuration query | **Confirmed** |
| `0x04` | Host ↔ Device | Configuration query | **Confirmed** |
| `0x10` | Host ↔ Device | Unknown | **Observed** |
| `0x11` | Host ↔ Device | Extended input stream control | **Confirmed / Established** |
| `0x12` | Host → Device | Rumble | **Confirmed / Established** |
| `0xA2` | Host → Device | Profile selection | **Established** |
| `0xEF` | Device → Host | Extended controller input | **Confirmed / Established** |
| `0xA8` / `0xA9` | Host ↔ Device | LED configuration | **Established externally** |

---

## `0x01` — Firmware / Device Information

Automatically received when the controller connects.

Example:

    5A A5 01 01 00 82 02 00 00 00 00 00 45 01 00 71
    53 04 67 35 15 00 00 00 00 00 00 10 26 1F 00 2F

Firmware fields use packed BCD:

| Bytes | Component |
|-------|-----------|
| 15–16 | Controller firmware |
| 17–18 | Dongle firmware |
| 19–20 | SI firmware |
| 27–28 | RF firmware |

Decoding:

    AA BB → (AA >> 4).(AA & 0x0F).(BB >> 4).(BB & 0x0F)

Example:

    71 53 → 7.1.5.3
    04 67 → 0.4.6.7
    35 15 → 3.5.1.5
    10 26 → 1.0.2.6

**Status: Confirmed from direct captures.**

---

## `0xA1` — Device Information / Capabilities

Observed connection request:

    5A A5 A1 02 A3

Observed response:

    5A A5 A1 01 00 02 56 56 4D A5 03 2B 58 AE E6 32
    FF FF FF FF FF FF 00 00 00 00 00 00 00 00 00 88

Occurs immediately after the `0x01` firmware information packet.

The command is used for device/capability information.

Individual response fields are not fully decoded.

**Status: Confirmed / Established.**

---

## `0x02` — Status / Configuration Query

Observed request:

    5A A5 02 02 04

Observed response:

    5A A5 02 01 00 FF FF FF FF FF FF FF FF FF FF FF
    FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF E9

Occurs during controller connection initialization.

The detailed response fields remain undecoded.

**Status: Confirmed request/response; payload semantics unknown.**

---

## `0x04` — Configuration Query

Observed request:

    5A A5 04 02 06

Observed response:

    5A A5 04 01 00 14 20 6E 7A 1C 00 00 00 00 08 16
    31 02 00 00 00 00 00 00 00 00 00 00 00 00 00 8E

Occurs during controller connection initialization.

The response contains stable configuration data.

Individual fields remain undecoded.

**Status: Confirmed request/response.**

---

## `0x10` — Unknown

Observed during the controller connection sequence:

    5A A5 10 02 12

Response:

    5A A5 10 01 00 01 00 00 00 00 ...

The transaction is retained because it is directly present in USBPcap
captures.

Its semantic purpose has not been established.

It is **not classified as a heartbeat** in this reference.

**Status: Observed; function unknown.**

---

## `0x11` — Extended Input Stream Control

Enable:

    5A A5 11 07 FF 01 FF FF FF 15

Disable:

    5A A5 11 07 FF 00 FF FF FF 14

Enabling the stream causes Interface 1 to produce `0xEF` extended
controller reports.

These reports contain:

- Standard buttons
- M1–M4
- LM/RM
- C/Z
- Home
- FN/Share
- Left/right sticks
- Triggers
- Gyroscope
- Accelerometer

Disabling the stream returns Interface 1 to its non-streaming state.

**Status: Confirmed / Established.**

---

## `0x12` — Rumble

Rumble command:

    5A A5 12 06 SS WW 00 00 00 00

Where:

- `SS` = strong/heavy rumble motor intensity
- `WW` = weak/light rumble motor intensity
- Range: `0x00–0xFF`

The Vader 5 Pro has two physically different rumble motors:

- One produces a heavier, stronger, lower-frequency vibration.
- The other produces a lighter, higher-frequency vibration.

Direct hardware testing confirms that the two channels can be driven
independently and produce clearly different physical responses.

The protocol fields therefore represent **two independent motor channels**
rather than simply a single rumble intensity value.

Examples:

    5A A5 12 06 FF 00 00 00 00 00
    5A A5 12 06 00 FF 00 00 00 00
    5A A5 12 06 FF FF 00 00 00 00
    5A A5 12 06 00 00 00 00 00 00

The exact physical left/right assignment of `SS` and `WW` should be
verified separately; the important confirmed distinction is that the two
channels drive the two different motor types.

`padctl` independently implements the same Vader 5 Pro output structure
using separate `strong` and `weak` motor fields.

**Status: Confirmed / Established.**

---

## `0xA2` — Profile Selection

`padctl` and independent Vader 5 Pro implementations identify `0xA2`
as a profile-selection command.

Profile values are associated with controller output/profile modes.

Exact command variants and all profile values are not yet documented here.

**Status: Established externally; further local testing desirable.**

---

## `0xEF` — Extended Controller Input

Interface 1 extended input report.

Header:

    5A A5 EF ...

`padctl` establishes the following report structure:

| Offset | Field |
|--------|-------|
| 3–4 | Left X |
| 5–6 | Left Y |
| 7–8 | Right X |
| 9–10 | Right Y |
| 11–12 | Standard button state |
| 13 | Extended button state |
| 14 | Additional buttons / state |
| 15 | Left trigger |
| 16 | Right trigger |
| 17–22 | Gyroscope |
| 23–28 | Accelerometer |
| 29–31 | Additional state / reserved |

Known extended controls include:

- M1–M4
- LM/RM
- C/Z
- Home
- FN/Share
- Standard ABXY / D-pad / system controls
- Gyroscope
- Accelerometer

`padctl` also establishes the required signed integer interpretation,
axis handling, and motion-data transformations used by its Vader 5 Pro
mapping.

**Status: Confirmed / Established.**

---

## `0xA8` / `0xA9` — LED Configuration

ControlLab independently recovered the Vader 5 USB lighting protocol and
checked its implementation against the official Flydigi Space Station
4.2.0.9 controller library.

The lighting protocol uses New XInput `0xA8` / `0xA9` chunk packets.

Known configurable lighting properties include:

- LED effect / mode
- Brightness
- Animation cycle time
- Color data
- Multiple colors for supported effects

Known effect types include:

- Default
- Flow
- Breathing
- Feedback
- Gradient
- Steady
- Off

The exact packet/chunk layout and field offsets are not yet included here.

This is a separate configuration protocol from the normal `5A A5`
controller input/rumble commands.

**Status: Established externally; not yet locally tested.**

---

## Battery Status

No battery-status packet or field has yet been established with sufficient
confidence.

Potential candidates include fields in the existing `0x01`, `0x02`,
`0x04`, or `0xA1` responses, but none should currently be labelled as
battery data without controlled testing.

Useful future tests:

- Capture the same response at substantially different battery levels.
- Compare controller connected/disconnected states.
- Compare charging vs. not charging, if applicable.
- Look for fields that change while all controller inputs remain unchanged.

**Status: Open investigation.**

---

## Connection Initialization

Direct USBPcap captures show the following sequence:

    Device → Host
    5A A5 01 ...

    Host → Device
    5A A5 A1 02 A3

    Host → Device
    5A A5 02 02 04

    Host → Device
    5A A5 04 02 06

    Host → Device
    5A A5 10 02 12

    Host → Device
    5A A5 11 07 FF 00 FF FF FF 14

A second `0x01` packet is subsequently observed.

The `0x10` transaction is part of the captured sequence, but its purpose
remains unknown.

---

## Extended Input Mapping

The following is established by `padctl` and should be treated as the
current reference mapping rather than an unverified reverse-engineering
hypothesis.

| Data | Function |
|------|----------|
| Left X/Y | Left analogue stick |
| Right X/Y | Right analogue stick |
| LT / RT | Analogue triggers |
| Standard button bits | ABXY / D-pad / system controls |
| Extended button bits | M1–M4, LM, RM, C, Z, Home and other auxiliary controls |
| Gyro fields | 3-axis angular motion |
| Accelerometer fields | 3-axis linear acceleration |

`padctl` performs the required signed decoding and axis transformations
for the Vader 5 Pro.

---

## Known Output Functions

| Function | Command | Status |
|----------|---------|--------|
| Extended input enable | `0x11` | **Confirmed** |
| Extended input disable | `0x11` | **Confirmed** |
| Rumble | `0x12` | **Confirmed** |
| Profile selection | `0xA2` | **Established** |
| LED configuration | `0xA8` / `0xA9` | **Established externally** |

Additional vendor output functions may exist but have not yet been
sufficiently identified.

---

## Important Connection-Detection Note

`0xEF` traffic alone is **not** a reliable controller-presence indicator.

USBPcap captures show the dongle can emit an identical `0xEF` packet while
the controller is absent.

Likewise, USB HID interface enumeration alone does not prove that the
controller is connected.

The most reliable currently observed disconnect indication is the loss of
the HID interfaces / corresponding HID communication.

---

## Remaining High-Value Unknowns

| Item | Status |
|------|--------|
| `0x01` byte 11 (`0x00` / `0x05`) | Unknown |
| `0xA1` individual fields | Partially decoded |
| `0x02` payload fields | Unknown |
| `0x04` payload fields | Unknown |
| `0x10` function | Unknown |
| `0xA2` complete profile table | Partially documented |
| `0xA8` / `0xA9` exact LED packet layout | Known externally, not yet locally mapped |
| Battery status / battery field | Unknown |
| `0x81` capdata | Unknown |
| Additional vendor output commands | Unknown |

---

## Independent References

- `BANANASJIM/padctl` — Linux HID/gamepad implementation with a dedicated
  Vader 5 Pro device definition and working extended-input/rumble handling.
- `dracinn/ControlLab` — independent Vader 5 Pro protocol implementation,
  including recovered USB LED configuration.
- `vader5pro-remap-driver` — independent Vader 5 Pro protocol and mapping
  implementation.

Direct USBPcap captures and hardware tests remain the primary evidence for
packet ordering and device-specific observations. External implementations
are used to establish semantics where they independently implement the
same behavior.
