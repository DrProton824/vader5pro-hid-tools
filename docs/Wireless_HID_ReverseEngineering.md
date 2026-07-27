# VID 37D7 PID 2401 | HID Reverse Engineering Notes

## Device

- Flydigi Flysync™ Vader 5 Pro (USB dongle)
- **VID:** `0x37D7`
- **PID:** `0x2401`

The dongle exposes 4 different HID interfaces

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
- No Traffic/Communication on all 4 HID Interfaces.

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

- All 4 HID interfaces reappear.
- Traffic/Communication on Interface 0 and 1.
  - Short initialization burst on Interface 1.
  - After initialization, heartbeat packet is sent about once every 30 seconds on Interface 1.
- No Traffic/Communication on Interface 3 and 4.

---

## Conclusions

**HID Interface presence alone is NOT a reliable controller connection detector.**

The dongle may enumerate HID interfaces while no controller is connected to the dongle.


Reliable observations:

- Communication on Interface 1 indicates the controller has connected.
- Interface disappearance is a reliable disconnect signal.

---

# HID Interface List

When active, the dongle exposes four HID interfaces.

## Interface 0

| Property | Value |
|----------|-------|
| Usage Page | `0x0001` |
| Usage | `0x0005` |

Observed behaviour:

- Reports only during controller inputs.
- Carries standard controller input:
- No heartbeat.
- No startup sequence.
- No vendor-only buttons observed (LM, RM, C, Z, M1-M4).
- No gyro data observed.

**Likely:** XInput-compatible HID interface (descriptor not yet verified).

---

## Interface 1

| Property | Value |
|----------|-------|
| Usage Page | `0xFFA0` |
| Usage | `0x0001` |

Vendor-specific communication interface.

Observed behaviour:

Before handshake initialization:
- Startup sequence
- Heartbeat every ~30 seconds
- No continuous input stream

After handshake initialization:
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

Exact purpose currently unknown.

---

## Interface 3

| Property | Value |
|----------|-------|
| Usage Page | `0xFFEE` |
| Usage | `0x0000` |

Exact purpose currently unknown.

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

The exact report descriptor and field layout have not been decoded.

---


# Interface 1 Packet Format

Report length:
- 32 bytes

Header:
| Byte | Meaning |
|------|---------|
| 0 | `0x5A` |
| 1 | `0xA5` |
| 2 | Command / packet type |
| 31 | Checksum / CRC |


# Startup Sequence

Whenever the wireless controller connects, Interface 1 immediately emits an initialization burst **without any host interaction**.

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

After this burst, Interface 1 becomes mostly idle and only emits heartbeat packets until initialized by the host.

Likely packet meanings:

| Type | Purpose |
|------|---------|
| `0x01` | Device / controller information |
| `0xA1` | Controller capabilities |
| `0x02` | Status information |
| `0x04` | Configuration information |
| `0x10` | Heartbeat |
| `0x11` | Status / event response |

---

# Vendor Initialization (Handshake) via Interface 1

The vendor HID initialization sequence was recovered from the
reverse-engineered Vader5Protocol implementation in ControlLab:

https://github.com/dracinn/ControlLab

The implementation defines the following initialization commands:

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
- Vendor-only buttons:
  - M1-M4
  - LM/RM
  - C/Z
  - Home(Flydigi Logo)
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

# Heartbeat

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

1. Wait for Interface 1 ennumeration.
2. Locate Interface 1.
3. Open Interface 1.
4. Wait for the first valid packet.
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
