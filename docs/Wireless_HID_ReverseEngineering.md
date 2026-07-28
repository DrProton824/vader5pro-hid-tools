# VID 37D7 PID 2401 | HID Reverse Engineering Notes

## Device

- Flydigi Flysync™ Vader 5 Pro (USB dongle)
- **VID:** `0x37D7`
- **PID:** `0x2401`

The USB receiver exposes four HID interfaces (MI_00–MI_03), each implementing a different HID function.

---

# HID Interface Enumeration

The dongle exposes HID interfaces differently depending on startup order.

## Case A

Action:

- Dongle is currently unplugged
- Dongle gets plugged into the PC
- Controller remains OFF

Result:

- Four HID interfaces enumerate after dongle is plugged in.
- No traffic/communication on all 4 HID Interfaces.

---

## Case B

Sequence:
- Dongle is already plugged into the PC
- Controller is connected via dongle
- Controller is turned OFF

Result:

- After approximately **3–5 seconds**:
  - Windows plays the USB disconnect sound.
  - All four HID interfaces disappear.

Controller is turned ON again:

- All four HID interfaces reappear.
- Traffic/communication:
  - Interface 1:
      Emits a controller startup information sequence automatically.
      Remains mostly idle afterwards.
      Sends heartbeat packets approximately every 30 seconds.
  - Interface 0:
      Begins reporting standard controller input when input changes.
- No traffic/communication observed on Interface 2 and Interface 3.

---

## Conclusions

**HID Interface presence alone is NOT a reliable controller connection detector.**

The dongle may enumerate HID interfaces while no controller is connected to the dongle.


Reliable observations:

- Communication on Interface 1 indicates the controller has connected.
- Interface disappearance is a reliable disconnect signal.


---

# USB Interface List/Summary

When active, the dongle exposes four HID interfaces.

| Interface | USB MI | Usage | Purpose |
|-----------|---------|--------|---------|
| Interface 0 | MI_00 | Generic Desktop / Gamepad | Standard controller input |
| Interface 1 | MI_01 | Vendor (0xFFA0) | Vendor protocol / NewXInput |
| Interface 2 | MI_02 | Generic Desktop / Mouse | Mouse HID interface (unused during normal operation) |
| Interface 3 | MI_03 | Vendor (0xFFEE) | Vendor interface (purpose unknown) |


## Interface 0

| Property | Value |
|----------|-------|
| Usage Page | `0x0001` |
| Usage | `0x0005` |

Observed behaviour:

- Standard HID gamepad input interface.
- Does not require vendor initialization.
- Does not expose vendor-specific controls or motion sensors.
- Reports only when controller state changes.
- Carries standard controller input:
  - Buttons
  - D-pad
  - Analogue sticks
  - Triggers

Not observed:

- No heartbeat.
- No startup sequence.
- No vendor-only buttons (LM, RM, C, Z, M1-M4).
- No gyro data.
- No accelerometer data.

**Confirmed from the HID report descriptor:**

- Generic Desktop / Gamepad
- 14-byte input reports
- 10 buttons
- Hat switch
- Left stick (X/Y)
- Right stick (Rx/Ry)
- Triggers (Z/Rz)

No vendor-defined usages are present in the descriptor.


---

## Interface 1

| Property | Value |
|----------|-------|
| Usage Page | `0xFFA0` |
| Usage | `0x0001` |

Descriptor summary:

- 33-byte HID reports (32-byte payload + report ID slot)
- 32-byte input reports
- 32-byte output reports
- No feature reports

Vendor-specific NewXInput communication interface.
Requires the vendor initialization command sequence for full communication
including vendor input reports and extended controller data.

Observed behaviour:

Before vendor initialization:
- Startup sequence
- Heartbeat every ~30 seconds
- No continuous input stream

After vendor initialization:
- Continuous vendor input reports (`0xEF`)
- Standard buttons
- Vendor-only buttons
- Analogue sticks
- Gyroscope
- Additional vendor state

---

## Interface 2

| Property | Value |
|----------|-------|
| Usage Page | `0x0001` |
| Usage | `0x0002` |

Appears as a standard HID mouse interface.

Descriptor:

- Usage Page: Generic Desktop
- Usage: Mouse
- Report ID: 2
- 7-byte input reports
- Five buttons
- Relative X/Y movement
- Mouse wheel

No traffic has been observed during normal controller operation.
Its practical purpose remains unknown.

---

## Interface 3

| Property | Value |
|----------|-------|
| Usage Page | `0xFFEE` |
| Usage | `0x0000` |

Vendor-defined HID interface.

Descriptor:

- Usage Page: 0xFFEE
- 64-byte input reports
- 64-byte output reports
- 64-byte feature reports
- Report ID: 5

No traffic has been observed during normal controller operation.
Its practical purpose remains unknown.

---

# Interface 0 Packet Format

Report length:
- 14 bytes

Observed characteristics:
- No packet header.
- No packet type field.
- No checksum or CRC observed.
- Reports are emitted only when controller state changes.
- No startup sequence.
- No heartbeat.


Example observations:

- Bytes 0–9 appear to contain analogue stick and trigger values.
- Bytes 10–13 appear to contain button state bits.

The HID descriptor confirms the following report contents:

- Buttons 1–10
- Hat switch
- Left stick (X/Y)
- Right stick (Rx/Ry)
- Two analogue triggers

The exact byte offsets within the 14-byte report have not yet been mapped.

---


# Interface 1 Packet Format

Report length:
- 32 bytes

| Byte | Meaning |
|------|---------|
| 0 | Packet magic `0x5A` |
| 1 | Packet magic `0xA5` |
| 2 | Command / report type |
| 3 | Payload length |
| 4+ | Payload data |
| Last used byte | 8-bit additive checksum |
| Remaining bytes | Zero padding |


## Startup Sequence

Whenever the wireless controller connects, Interface 1 automatically emits an initialization burst **without any host interaction**.

Typical sequence:

```
5A A5 01 ...
5A A5 A1 ...
5A A5 02 ...
5A A5 04 ...
5A A5 10 ...
5A A5 11 ...
```

Example:

```
5A A5 01 01 00 82 02 ...
5A A5 A1 01 00 02 41 ...
5A A5 02 01 00 FF FF ...
5A A5 04 01 00 14 20 ...
5A A5 10 01 00 01 ...
5A A5 11 01 00 01 ...
```

The exact ordering may vary slightly.

After this burst, Interface 1 becomes mostly idle and only emits heartbeat/status packets until the host enables the vendor input stream.

Likely packet meanings:

| Type | Purpose |
|------|---------|
| `0x01` | Firmware/device information (contains firmware version fields) |
| `0xA1` | Capability / device information (exact format unknown) |
| `0x02` | Status information |
| `0x04` | Configuration information |
| `0x10` | Heartbeat |
| `0x11` | Event/status response |

---

## Packet `0x01` – Firmware Information

The `0x01` startup packet contains firmware version information for several
components of the controller.

Each firmware version is stored as **two packed BCD bytes**, where every
4-bit nibble represents one decimal digit.

For a two-byte firmware field:

```
AA BB
```

the version number is decoded as:

```
(AA >> 4).(AA & 0x0F).(BB >> 4).(BB & 0x0F)
```

Equivalent nibble layout:

```
Byte AA                 Byte BB

+--------+--------+     +--------+--------+
| High   | Low    |     | High   | Low    |
| nibble | nibble |     | nibble | nibble |
+--------+--------+     +--------+--------+
    V1       V2             V3       V4

Version = V1.V2.V3.V4
```

Examples:

| Raw bytes | Decoded version |
|-----------|-----------------|
| `71 53` | `7.1.5.3` |
| `04 67` | `0.4.6.7` |
| `35 15` | `3.5.1.5` |
| `10 26` | `1.0.2.6` |
| `12 34` | `1.2.3.4` |

Byte indices below are **zero-based** and refer to the complete 32-byte HID report.
For single-segment (Payload length = 1) 0x01 packets, the decoded firmware field layout is:

| Byte(s) | Meaning |
|---------|---------|
| 11 | Unknown — variable field |
| 12–14 | Unknown |
| 15–16 | Controller firmware |
| 17–18 | Dongle firmware |
| 19–20 | SI firmware |
| 21–26 | Unknown / padding |
| 27–28 | RF firmware |
| 29 | Unknown |

Example:

```
5A A5 01 01 00 82 02 00 00 00 00
?? 45 01 00
71 53
04 67
35 15
00 00 00 00 00 00
10 26
1F 00
CS
```

Decoded values:

| Component | Bytes | Raw | Version |
|-----------|-------|-----|---------|
| Controller | 15–16 | `71 53` | `7.1.5.3` |
| Dongle | 17–18 | `04 67` | `0.4.6.7` |
| SI | 19–20 | `35 15` | `3.5.1.5` |
| RF | 27–28 | `10 26` | `1.0.2.6` |

The purpose of bytes `11`, `12–14`, `29` and the padding region `21–26` is currently unknown.
A firmware field containing `00 00` or `FF FF` should be considered absent
or invalid rather than a real version number.

The reverse-engineered parser also supports segmented `0x01` packets
(payload length > 1). In those packets the firmware fields are shifted by
one byte due to the additional segment index byte. Only segment `0` is
interpreted by the parser.

---

## Vendor Initialization (Handshake) via Interface 1

The vendor HID initialization sequence was recovered from the
reverse-engineered Vader5Protocol implementation in ControlLab:

https://github.com/dracinn/ControlLab

The implementation defines the following initialization commands:
Source:
`Sources/Vader5Core/Vader5Protocol.swift`

```
5A A5 01 02 03
5A A5 A1 02 A3
5A A5 02 02 04
5A A5 04 02 06
5A A5 11 07 FF 01 FF FF FF 15
```

## Behaviour before initialization

During active controller connection but before initialization, Interface 1 provides:
- Controller information response
- Capability/status responses
- Heartbeat packets approximately every 30 seconds

However:
- No continuous vendor input reports are produced.
- Standard controller input remains available through Interface 0.
- Vendor-specific controls and motion data are not reported.


## Behaviour after initialization

After sending the initialization sequence, Interface 1 begins
producing vendor input reports:

- `0xEF` controller state reports
- Report format:
- 29+ byte reports
- Header:
    - Byte 0: `0x5A`
    - Byte 1: `0xA5`
    - Byte 2: `0xEF`
- Vendor-only buttons:
  - M1-M4
  - LM/RM
  - C/Z
  - Home (Flydigi logo)
- Standard buttons:
  - X/Y/A/B
  - Up/Down/Left/Right
  - Start/Select
  - FN/Share
- Gyroscope data
- Accelerometer data
- High-rate controller state updates

The following command disables the vendor input stream:

```
5A A5 11 07 FF 00 FF FF FF 14
```

After the stop command, Interface 1 returns to its passive
heartbeat/status behaviour.

The exact purpose of each initialization command was not further investigated.

---

## Heartbeat

Packet:

```
5A A5 10 01 00 01 00 00 00 01 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 13
```

Frequency:

- Approximately every **30 seconds**

Heartbeat should **not** be used for disconnect detection because:

- The interval is too long.
- Interface disappearance occurs much sooner.
- Loss of communication is observable before heartbeat timeout.

---

# Recommended Monitoring Logic

1. Wait for Interface 1 enumeration.
2. Locate Interface 1.
3. Open Interface 1.
4. Wait for the first valid Interface 1 packet (typically the automatic startup sequence).
5. Mark the controller as connected.
6. Send the recovered vendor initialization sequence if vendor reports are required.
7. Read vendor reports continuously.
8. Detect disconnect through interface disappearance (and read errors where applicable).

This approach combines:

- HID enumeration
- Passive connection detection
- Optional vendor initialization
- Continuous vendor report reading
- Immediate disconnect detection
