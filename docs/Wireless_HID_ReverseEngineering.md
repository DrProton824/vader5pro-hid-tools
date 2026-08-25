# VID 37D7 PID 2401 | HID Reverse Engineering Notes

## Device

- Flydigi Flysync™ Vader 5 Pro (USB dongle)
- **VID:** `0x37D7`
- **PID:** `0x2401`

The USB receiver exposes four HID interfaces (MI_00–MI_03), each implementing a different HID function.

Throughout this document:

- **Observed** = directly observed in USB/HID captures or HID descriptor data.
- **Derived** = calculated directly from observed data.
- **Inferred** = a working interpretation that is not yet independently confirmed.
- **External** = information obtained from another implementation or project and not yet independently verified here.

---

# HID Interface Enumeration

The dongle exposes HID interfaces even when no controller is connected. HID interface enumeration alone is therefore not a reliable controller connection detector.

## Case A

Action:

- Dongle is currently unplugged
- Dongle gets plugged into the PC
- Controller remains OFF

Result:

- Four HID interfaces enumerate after the dongle is plugged in.
- No traffic/communication is observed on any of the 4 HID interfaces.

**Observed.**

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
- Traffic/communication is observed:
  - Interface 1:
    - Emits a controller startup information sequence automatically.
    - Remains mostly idle afterwards.
    - Sends heartbeat packets approximately every 30 seconds.
  - Interface 0:
    - Begins reporting standard controller input when input changes.
- No traffic/communication has been observed on Interface 2 or Interface 3 during normal operation.

**Observed.**

---

## Conclusions

**HID interface presence alone is NOT a reliable controller connection detector.**

The dongle may enumerate HID interfaces while no controller is connected to the dongle.

Reliable observations from the current captures:

- Interface 1 traffic appears when the controller connects.
- Interface disappearance occurs when the controller is disconnected.
- Interface 1 traffic is therefore a useful **controller-presence indicator**, but its exact relationship to the underlying wireless connection has not been fully established.

---

# USB Interface List/Summary

When active, the dongle exposes four HID interfaces.

| Interface | USB MI | Usage | Purpose |
|-----------|---------|---------|---------|
| Interface 0 | MI_00 | Generic Desktop / Gamepad | Standard controller input |
| Interface 1 | MI_01 | Vendor (`0xFFA0`) | Vendor protocol / NewXInput |
| Interface 2 | MI_02 | Generic Desktop / Mouse | Mouse HID interface (unused during normal operation) |
| Interface 3 | MI_03 | Vendor (`0xFFEE`) | Vendor-defined interface (purpose unknown) |

The interface purposes above are based on HID descriptors and observed behaviour. Some purposes remain unconfirmed.

---

## Interface 0

| Property | Value |
|----------|-------|
| Usage Page | `0x0001` |
| Usage | `0x0005` |

Observed behaviour:

- Standard HID gamepad input interface.
- Does not require vendor initialization.
- Does not expose vendor-specific controls or motion sensors in the observed report descriptor.
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

- 32-byte input reports
- 32-byte output reports
- No feature reports

Vendor-specific NewXInput communication interface.

**Observed behaviour:**

Before vendor initialization:

- Startup information/status traffic is observed.
- Heartbeat traffic occurs approximately every 30 seconds.
- No continuous `0xEF` input stream is observed.

After the recovered initialization sequence is sent:

- Continuous vendor input reports (`0xEF`) are observed.
- Standard buttons are reported.
- Vendor-only buttons are reported.
- Analogue sticks are reported.
- Gyroscope data is reported.
- Accelerometer data is reported.
- Additional vendor state is present.

The exact role of every command in the initialization sequence has not yet been experimentally established.

> **HID descriptor vs. captured transfer length:** The HID descriptor contains report-ID information, while the captured vendor packets discussed below are 32-byte transfers beginning with `0x5A 0xA5`. These are documented separately to avoid conflating descriptor-level report structure with the captured wire-level packet format.

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

- Usage Page: `0xFFEE`
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

Captured report length:

- 32 bytes

For the vendor protocol packets observed so far:

| Byte | Meaning |
|------|---------|
| 0 | Packet magic `0x5A` |
| 1 | Packet magic `0xA5` |
| 2 | Command / report type |
| 3 | Payload/segment length field |
| 4+ | Payload data |
| Variable | Candidate checksum field |
| Remaining bytes | Padding / unused data |

The exact meaning of byte 3 is not yet fully established for every packet type. It should therefore not be treated as a universal payload-length field until additional packet types have been verified.

A checksum appears to be present near the end of the populated portion of the packet. An additive relationship has been observed in captured packets, but the complete checksum algorithm has not yet been independently verified across all packet types.

---

# Known Interface 1 `0xEF` Controller Report Mapping

The extended controller report uses the following 32-byte format.

The mapping below is currently supported by multiple independent implementations and protocol descriptions, including ControlLab, padctl, and the `vader5pro-remap-driver` project.

**Important:** The existence and general layout of these fields are externally corroborated. Individual button assignments, axis polarity, IMU scaling, and exact semantics should still be considered **pending direct verification against local captures** unless explicitly marked as confirmed.

## Report Structure

Reports begin with:

```text
5A A5 EF
```

| Byte(s) | Size | Field | Type | Status |
|---------|------|-------|------|--------|
| 0–2 | 3 | Magic / report type | `u8[3]` | Confirmed |
| 3–4 | 2 | Left stick X | `i16le` | Cross-source |
| 5–6 | 2 | Left stick Y | `i16le` | Cross-source; negate |
| 7–8 | 2 | Right stick X | `i16le` | Cross-source |
| 9–10 | 2 | Right stick Y | `i16le` | Cross-source; negate |
| 11 | 1 | Standard buttons 1 | bitfield | Cross-source |
| 12 | 1 | Standard buttons 2 | bitfield | Cross-source |
| 13 | 1 | Extended buttons 1 | bitfield | Cross-source |
| 14 | 1 | Extended buttons 2 | bitfield | Cross-source |
| 15 | 1 | Left trigger | `u8` | Cross-source |
| 16 | 1 | Right trigger | `u8` | Cross-source |
| 17–18 | 2 | Gyroscope X | `i16le` | Cross-source |
| 19–20 | 2 | Gyroscope Y | `i16le` | Cross-source |
| 21–22 | 2 | Gyroscope Z | `i16le` | Cross-source |
| 23–24 | 2 | Accelerometer X | `i16le` | Cross-source |
| 25–26 | 2 | Accelerometer Y | `i16le` | Cross-source |
| 27–28 | 2 | Accelerometer Z | `i16le` | Cross-source |
| 29–31 | 3 | Reserved / unknown | `u8[3]` | Cross-source |

---

## Stick Mapping

All four stick axes are encoded as signed 16-bit little-endian integers.

| Bytes | Field | Type | Transform |
|--------|-------|------|-----------|
| 3–4 | Left X | `i16le` | None |
| 5–6 | Left Y | `i16le` | Negate |
| 7–8 | Right X | `i16le` | None |
| 9–10 | Right Y | `i16le` | Negate |

The Y-axis negation is required by the existing protocol implementations to convert the device's coordinate direction into the conventional gamepad coordinate system.

The exact native range, center point, and calibration behaviour should be determined from additional captures.

---

## Trigger Mapping

Triggers are unsigned 8-bit values.

| Byte | Field | Type | Expected range |
|------|-------|------|----------------|
| 15 | Left trigger (LT) | `u8` | `0x00–0xFF` |
| 16 | Right trigger (RT) | `u8` | `0x00–0xFF` |

No additional scaling is currently known to be required.

---

## Standard Button Mapping

### Byte 11 — Buttons 1

| Bit | Button |
|-----|--------|
| 0 | D-pad Up |
| 1 | D-pad Down |
| 2 | D-pad Left |
| 3 | D-pad Right |
| 4 | A |
| 5 | B |
| 6 | Select / Back |
| 7 | X |

### Byte 12 — Buttons 2

| Bit | Button |
|-----|--------|
| 0 | Y |
| 1 | Start |
| 2 | LB |
| 3 | RB |
| 4 | Unknown / unused |
| 5 | Unknown / unused |
| 6 | L3 |
| 7 | R3 |

The exact naming of the Select/Back and Start buttons may differ between software layers. The underlying bit positions are the important part.

---

## Extended Button Mapping

### Byte 13 — Extended Buttons

| Bit | Button |
|-----|--------|
| 0 | C |
| 1 | Z |
| 2 | M1 |
| 3 | M2 |
| 4 | M3 |
| 5 | M4 |
| 6 | LM |
| 7 | RM |

This byte contains the rear/auxiliary controls that are not represented by the standard HID gamepad interface.

### Byte 14 — Extended Buttons 2

| Bit | Button |
|-----|--------|
| 0 | O / Fn |
| 1 | Unknown / unused |
| 2 | Unknown / unused |
| 3 | Home |
| 4–7 | Unknown / unused |

The `O` / `Fn` naming differs between sources and software implementations. Treat the underlying bit as the confirmed property until the physical label/function is independently verified.

---

## IMU Mapping

The `0xEF` report contains six signed 16-bit little-endian IMU values.

### Gyroscope

| Bytes | Field | Type |
|--------|-------|------|
| 17–18 | Gyro X | `i16le` |
| 19–20 | Gyro Y | `i16le` |
| 21–22 | Gyro Z | `i16le` |

### Accelerometer

| Bytes | Field | Type |
|--------|-------|------|
| 23–24 | Accelerometer X | `i16le` |
| 25–26 | Accelerometer Y | `i16le` |
| 27–28 | Accelerometer Z | `i16le` |

Known axis transforms:

| Field | Transform |
|-------|-----------|
| Gyro X | None |
| Gyro Y | Negate |
| Gyro Z | None |
| Accelerometer X | None |
| Accelerometer Y | None |
| Accelerometer Z | None |

One independent protocol implementation reports an accelerometer scale of approximately **4096 counts per 1 g**. This should be treated as **externally reported, not yet locally verified**.

No final physical-unit conversion for gyro or accelerometer data is currently claimed by this document.

---

## Complete `0xEF` Byte Map

For quick reference:

```text
Offset  Size  Description
------  ----  --------------------------------
0       1     Magic: 0x5A
1       1     Magic: 0xA5
2       1     Report type: 0xEF

3-4     2     Left stick X       i16 LE
5-6     2     Left stick Y       i16 LE, negate
7-8     2     Right stick X      i16 LE
9-10    2     Right stick Y      i16 LE, negate

11      1     Buttons 1
12      1     Buttons 2
13      1     Extended buttons
14      1     Extended buttons 2

15      1     Left trigger      u8
16      1     Right trigger     u8

17-18   2     Gyro X            i16 LE
19-20   2     Gyro Y            i16 LE, negate
21-22   2     Gyro Z            i16 LE

23-24   2     Accelerometer X   i16 LE
25-26   2     Accelerometer Y   i16 LE
27-28   2     Accelerometer Z   i16 LE

29-31   3     Reserved / unknown
```

---

## Startup Sequence

Whenever the wireless controller connects, Interface 1 automatically emits an information/status burst without any host interaction.

Typical observed packet types:

```text
5A A5 01 ...
5A A5 A1 ...
5A A5 02 ...
5A A5 04 ...
5A A5 10 ...
5A A5 11 ...
```

Example captured packet prefixes:

```text
5A A5 01 01 00 82 02 ...
5A A5 A1 01 00 02 41 ...
5A A5 02 01 00 FF FF ...
5A A5 04 01 00 14 20 ...
5A A5 10 01 00 01 ...
5A A5 11 01 00 01 ...
```

The exact ordering may vary slightly between connections.

After this burst, Interface 1 becomes mostly idle and emits periodic heartbeat/status traffic until the host enables the vendor input stream.

### Observed / inferred packet meanings

| Type | Purpose | Confidence |
|------|---------|------------|
| `0x01` | Firmware/device information; contains firmware version fields | High |
| `0xA1` | Capability/device information | Inferred |
| `0x02` | Status information | Inferred |
| `0x04` | Configuration information | Inferred |
| `0x10` | Heartbeat | High |
| `0x11` | Event/status or control response | Inferred |

The semantic names above should be treated as working descriptions unless explicitly marked as experimentally confirmed.

---

## Packet `0x01` – Firmware Information

The `0x01` startup packet contains firmware version information for several components of the controller/dongle system.

Each firmware version is stored as **two packed BCD bytes**, where every 4-bit nibble represents one decimal digit.

For a two-byte firmware field:

```text
AA BB
```

the version number is decoded as:

```text
(AA >> 4).(AA & 0x0F).(BB >> 4).(BB & 0x0F)
```

Equivalent nibble layout:

```text
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

Byte indices below are **zero-based** and refer to the complete 32-byte captured HID packet.

For single-segment (`Payload length = 1`) `0x01` packets, the decoded firmware field layout is:

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

```text
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

The purpose of bytes `11`, `12–14`, `29` and the region `21–26` is currently unknown.

A firmware field containing `00 00` or `FF FF` should be treated as absent/invalid unless further captures demonstrate otherwise.

The reverse-engineered parser also supports segmented `0x01` packets (`Payload length > 1`). In those packets, an additional segment/index byte appears to shift the firmware fields by one byte. This interpretation is based on the parser implementation and has not yet been independently validated against a complete multi-segment capture.

Only segment `0` is currently interpreted by the parser.

---

## Vendor Initialization Sequence via Interface 1

A vendor HID initialization sequence has been identified in the reverse-engineered Vader 5 protocol implementation in ControlLab.

External source:

https://github.com/dracinn/ControlLab

Implementation:

`Sources/Vader5Core/Vader5Protocol.swift`

The implementation defines the following initialization commands:

```text
5A A5 01 02 03
5A A5 A1 02 A3
5A A5 02 02 04
5A A5 04 02 06
5A A5 11 07 FF 01 FF FF FF 15
```

**External / not yet independently derived from the current captures.**

These commands are therefore treated as a recovered working initialization sequence rather than as a fully reverse-engineered handshake.

---

## Behaviour before initialization

During an active controller connection but before the vendor initialization sequence is sent, Interface 1 provides:

- Controller information/status responses
- Periodic heartbeat packets approximately every 30 seconds

Observed:

- No continuous `0xEF` vendor input stream.
- Standard controller input remains available through Interface 0.

Not yet independently established:

- Whether all vendor-specific controls are completely absent before initialization.
- Whether motion data is unavailable at the protocol source or simply not exposed through the uninitialized stream.

---

## Behaviour after initialization

After sending the recovered initialization sequence, Interface 1 begins producing vendor input reports:

- `0xEF` controller state reports
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

The exact byte offsets, bit assignments, scaling, and semantics of the `0xEF` payload are not yet fully mapped in this document.

The following command disables the vendor input stream:

```text
5A A5 11 07 FF 00 FF FF FF 14
```

After the stop command, Interface 1 returns to its passive heartbeat/status behaviour.

The exact purpose of each initialization command has not yet been experimentally isolated.

---

## Heartbeat

Packet:

```text
5A A5 10 01 00 01 00 00 00 01 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 13
```

Frequency:

- Approximately every **30 seconds**

Observed:

- The packet repeats periodically while the controller remains connected.
- The packet type is consistently `0x10` in the observed captures.

Heartbeat should **not** be used as the sole disconnect detector because:

- The interval is too long.
- Interface disappearance occurs much sooner.
- Loss of communication can be observable before a heartbeat timeout.

---

# Recommended Monitoring Logic

1. Wait for Interface 1 enumeration.
2. Locate Interface 1.
3. Open Interface 1.
4. Wait for the first valid Interface 1 packet, typically the automatic startup sequence.
5. Mark the controller as **likely connected**.
6. Send the recovered vendor initialization sequence if vendor reports are required.
7. Read vendor reports continuously.
8. Detect disconnect through interface disappearance and/or HID read errors.
9. Treat heartbeat timeout as a secondary diagnostic signal rather than the primary disconnect detector.

This approach combines:

- HID enumeration
- Passive controller-presence detection
- Optional vendor initialization
- Continuous vendor report reading
- Immediate disconnect detection
