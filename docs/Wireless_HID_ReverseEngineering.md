# VID 37D7 PID 2401 | HID Reverse Engineering Notes

## Device

- Flydigi Flysync™ Vader 5 Pro (USB dongle)
- **VID:** `0x37D7`
- **PID:** `0x2401`

The dongle exposes 4 different HID interfaces

---

# HID Interface Enumeration

The dongle exposes hid interfaces differently depending on startup order.

## Case A

Sequence:

- Dongle unplugged
- Dongle plugged into the PC
- Controller remains OFF

Result:

- Four HID interfaces enumerate.
- No Traffic/Communication on all 4 HID Interfaces.

---

## Case B

Sequence:
- Dongle already plugged into the PC
- Controller is turned OFF

Result:

- After approximately **3–5 seconds**:
  - Windows plays the USB disconnect sound.
  - All four HID interfaces disappear.

Controller is turned ON again:

- HID interfaces reappear.
- Traffic/Communication on Interface 0 and 1.
- No Traffic/Communication on Interface 3 and 4.

---

## Conclusions

**Interface presence alone is NOT a reliable controller connection detector.**

The dongle may enumerate while no wireless controller is connected.

Reliable observations:

- First communication on Interface 1 indicates the controller has connected.
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

- Reports only when controller input changes.
- Carries standard controller input:
  - Buttons
  - Triggers
  - Analogue sticks
- No heartbeat.
- No startup sequence.
- No vendor-only buttons observed.
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

Before host initialization:

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

Purpose currently unknown.

---

## Interface 3

| Property | Value |
|----------|-------|
| Usage Page | `0xFFEE` |
| Usage | `0x0000` |

Purpose currently unknown.

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

---

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

# Vendor Initialization (Handshake)

Firmware analysis recovered the following initialization sequence:

```
5A A5 01 02 03
5A A5 A1 02 A3
5A A5 02 02 04
5A A5 04 02 06
5A A5 11 07 FF 01 FF FF FF 15
```

Observed behaviour before initialization:

- Startup sequence
- Heartbeat every ~30 seconds
- No continuous vendor input

Observed behaviour after initialization:

- Continuous `0xEF` input reports
- Standard controls
- Vendor-only buttons
- Gyroscope
- High-rate controller state updates

The following command stops the vendor stream:

```
5A A5 11 07 FF 00 FF FF FF 14
```

After the stop command, Interface 1 returns to its passive heartbeat-only behaviour.

The exact purpose of each initialization command is currently unknown.

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

1. Locate Interface 1.
2. Open Interface 1.
3. Wait for the first valid packet.
4. Mark the controller as connected.
5. Send the recovered vendor initialization sequence if vendor reports are required.
6. Read vendor reports continuously.
7. Detect disconnect through interface disappearance (and read errors where applicable).

This approach combines:

- HID enumeration
- Passive connection detection
- Optional vendor initialization
- Continuous vendor report reading
- Immediate disconnect detection
