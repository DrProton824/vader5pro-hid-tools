# VID 37D7 PID 2401 | USBPcap ReverseEngineering

## Overview

These notes document observed USB traffic on Interface 1 (MI_01, Usage Page `0xFFA0`) of the Flydigi Vader 5 Pro dongle, captured using USBPcap and analysed with tshark.

All observations are based on raw packet captures. Nothing in this document is inferred or assumed beyond what the captures directly show.

---

# Capture Methodology

All captures were taken with USBPcap targeting the dongle device.  
tshark was used to extract packet data from the resulting `.pcapng` files.  
Two data sources were captured per session:

- `usbhid.data` — HID report data on endpoints `0x06` (OUT) and `0x82` (IN)
- `usb.capdata` — Raw capture data on endpoint `0x81`

---

# Observed Endpoints

| Endpoint | Direction | Transfer Type | Observed Data |
|----------|-----------|---------------|---------------|
| `0x06` | OUT (host → device) | Interrupt | HID output reports (`5A A5` protocol) |
| `0x82` | IN (device → host) | Interrupt | HID input reports (`5A A5` protocol) |
| `0x81` | IN (device → host) | Interrupt | Raw capdata (20 bytes, not `5A A5` protocol) |

---

# Baseline Traffic (Dongle Connected, Controller Disconnected)

Captured with dongle plugged in, controller OFF.

Observed:

- Continuous OUT requests on `0x06`:

```
5A A5 01 02 03 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

- Continuous IN responses on `0x82`:

```
5A A5 EF 08 01 00 39 00 01 00 32 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

- Approximate cadence: one OUT/IN pair every ~0.5 seconds
- No `0x81` capdata observed
- No startup sequence observed
- No `0xA1`, `0x02`, `0x04`, `0x10`, or `0x11` packets observed

The `0xEF` response is present even with no controller connected.  
**The `0xEF` packet alone cannot be used to confirm controller presence.**

## Capdata observations (0x81)

`0x81` capdata only appears during and immediately after the connection initialization sequence.

### Device behavior after ~30-45 seconds idle

When the dongle remains without a connected controller for approximately 30-45 seconds,
the device performs a USB re-enumeration event (GET_DESCRIPTOR requests on endpoint `0x80`).

**Before re-enumeration:**

- OUT `0x01` polling requests: continuous (~0.5s cadence)
- IN `0xEF` responses: continuous

**After re-enumeration:**

- OUT `0x01` polling requests **stop permanently**
- ONLY `0xEF` IN packets continue, approximately **1 per second**
- This traffic pattern becomes **identical** to controller-connected idle state
- Pattern persists indefinitely (confirmed through extended capture)

**Critical implication:** After the re-enumeration event, dongle-only and 
controller-connected traffic become **completely indistinguishable**. The OUT `0x01` 
polling pattern cannot be used as a reliable connection detector beyond the initial phase.

**Windows behavior:** A USB disconnect sound is heard when the re-enumeration completes.

---

# Baseline Traffic (Controller Connected, Idle, Without TurnOn/Connect Sequence)

Captured with dongle plugged in, controller ON and Connected and Idling (no TurnOn/Connect included).

Observed:

- ONLY `0xEF` IN packets on `0x82`, one per second:

```
5A A5 EF 08 01 00 39 00 01 00 32 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

- No OUT requests observed during idle period
- No `0x81` capdata observed
- Packet content identical to the no-controller baseline

**The `0xEF` packet content does not change between controller-absent and controller-present states in idle conditions.**

---

# Controller Connection Sequence

Observed across three independent connection captures (`connect1`, `connect2`, `connect3`).

## Phase 1 — Pre-connection polling

Before the controller connects, the dongle sends repeated OUT requests:

```
5A A5 01 02 03 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

The dongle responds to each with:

```
5A A5 EF 08 01 00 39 00 01 00 32 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

This polling continues until the controller connects.

## Phase 2 — Controller connects

When the controller connects, the following packet appears on `0x82` IN,
triggered automatically without host interaction:

```
5A A5 01 01 00 82 02 00 00 00 00 00 45 01 00 71
53 04 67 35 15 00 00 00 00 00 00 10 26 1F 00 2F
```

Immediately after, the host sends the following OUT requests in sequence,
and the device responds to each:

**Exchange 1 — Capability query (`0xA1`)**

OUT:
```
5A A5 A1 02 A3 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

IN:
```
5A A5 A1 01 00 02 56 56 4D A5 03 2B 58 AE E6 32
FF FF FF FF FF FF 00 00 00 00 00 00 00 00 00 88
```

**Exchange 2 — Status query (`0x02`)**

OUT:
```
5A A5 02 02 04 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

IN:
```
5A A5 02 01 00 FF FF FF FF FF FF FF FF FF FF FF
FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF E9
```

**Exchange 3 — Configuration query (`0x04`)**

OUT:
```
5A A5 04 02 06 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

IN:
```
5A A5 04 01 00 14 20 6E 7A 1C 00 00 00 00 08 16
31 02 00 00 00 00 00 00 00 00 00 00 00 00 00 8E
```

**Exchange 4 — Heartbeat (`0x10`)**

OUT:
```
5A A5 10 02 12 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

IN:
```
5A A5 10 01 00 01 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 12
```

**Exchange 5 — Event/status (`0x11`)**

OUT:
```
5A A5 11 07 FF 00 FF FF FF 14 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

IN:
```
5A A5 11 01 00 01 00 00 00 14 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 27
```

Observed across all three captures:

- Sequence order is consistent
- Response payloads are **identical** across all three captures
- The `0x01` IN packet appears **twice** during connection (see Phase 3)

## Phase 3 — Second 0x01 packet

Shortly after the initialization sequence completes, a second `0x01` IN packet appears:

```
5A A5 01 01 00 82 02 00 00 00 00 05 45 01 00 71
53 04 67 35 15 00 00 00 00 00 00 10 26 1F 00 34
```

Compared to the first:

```
First:   5A A5 01 01 00 82 02 00 00 00 00 00 45 ...  checksum 2F
Second:  5A A5 01 01 00 82 02 00 00 00 00 05 45 ...  checksum 34
```

**Byte 11 differs: `0x00` in the first packet, `0x05` in the second.**  
The checksum difference (`0x2F` vs `0x34`) is consistent with a 5-unit
increase, confirming byte 11 is the only change.  
The meaning of byte 11 is not yet known.

## Phase 4 — Post-connection idle

After the sequence completes, Interface 1 emits `0xEF` packets at
approximately **1-second intervals**:

```
5A A5 EF 08 01 00 39 00 01 00 32 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

Content is identical to the no-controller baseline.

---

# Endpoint 0x81 Capdata

Three `0x81` packets are observed during every connection sequence.  
They do not follow the `5A A5` protocol.

## Packet 1 — Always identical

Appears immediately after the `0xA1` exchange:

```
00 14 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

## Packet 2 — Bytes 6–7 vary per connection

Appears immediately after the `0x02`/`0x04` exchange:

| Capture | Bytes 6–7 | Full packet |
|---------|-----------|-------------|
| `connect` | `C0 FB` | `00 14 00 00 00 00 C0 FB 00 00 00 00 00 00 00 00 00 00 00 00` |
| `connect1` | `C0 FB` | `00 14 00 00 00 00 C0 FB 00 00 00 00 00 00 00 00 00 00 00 00` |
| `connect2` | `80 FB` | `00 14 00 00 00 00 80 FB 00 00 00 00 00 00 00 00 00 00 00 00` |
| `connect3` | `40 FD` | `00 14 00 00 00 00 40 FD 00 00 00 00 00 00 00 00 00 00 00 00` |

Bytes 6–7 change between connections.  
The meaning is not known.  
It does not correlate with any visible protocol state.

## Packet 3 — Always identical

Appears several seconds after connection completes:

```
00 14 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

Identical to Packet 1.

## 0x81 Summary

- Never observed during no-controller baseline
- Never observed during controller-idle baseline
- Only observed during and immediately after the connection sequence
- Packet 1 and Packet 3 are always identical
- Packet 2 bytes 6–7 vary per connection session
- Purpose unknown

---

# Packet Consistency Summary

| Packet | Content consistent across captures? |
|--------|--------------------------------------|
| `0x01` first (firmware) | ✅ Yes — identical every connection |
| `0x01` second | ✅ Yes — identical every connection |
| `0xA1` response | ✅ Yes — identical every connection |
| `0x02` response | ✅ Yes — identical every connection |
| `0x04` response | ✅ Yes — identical every connection |
| `0x10` response | ✅ Yes — identical every connection |
| `0x11` response | ✅ Yes — identical every connection |
| `0xEF` idle packets | ✅ Yes — identical in all conditions |
| `0x81` packet 1 | ✅ Yes — identical every connection |
| `0x81` packet 2 | ❌ No — bytes 6–7 vary |
| `0x81` packet 3 | ✅ Yes — identical every connection |

---

# Open Questions

| Item | Status |
|------|--------|
| Meaning of `0x01` byte 11 (`0x00` vs `0x05`) | Unknown |
| Meaning of `0x81` packet 2 bytes 6–7 | Unknown |
| Whether `0xEF` content changes under button/stick input | Not yet captured |
| Whether any packet changes with battery level | Not yet captured |
| Which interface the `0x81` endpoint belongs to | Not yet confirmed |
| Purpose of `0x02` response payload (`FF FF FF...`) | Unknown |
| Purpose of `0x04` response payload | Unknown |
