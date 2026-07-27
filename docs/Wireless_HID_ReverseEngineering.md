============================================================
VID 37D7 PID 2401 - HID Controller Reverse Engineering Notes
============================================================

Device:
- USB wireless receiver dongle
- VID: 0x37D7
- PID: 0x2401


The dongle can expose or remove its HID interfaces depending
on the wireless controller connection state. 
There are TWO separate states:

1. USB dongle connected to PC
2. Wireless controller connected to dongle

------------------------------------------------------------
HID INTERFACE ENUMERATION
------------------------------------------------------------

The dongle can behave in different states depending on startup
order:

CASE A
Sequence:
- Dongle unplugged
- Plug dongle in
- Controller OFF
Result:
- 4 HID interfaces may appear immediately
However:
- Interfaces are silent
- No controller communication is present


CASE B
Sequence:
- Controller OFF
- Start monitoring
Result:
- No HID interfaces
Controller ON:
- 4 HID interfaces appear
- Interface 1 starts communication

CASE C
Sequence:
- Controller connected
- Turn controller OFF
Result:
- After approximately 3-5 seconds:
    - Windows USB disconnect sound
    - 4 HID interfaces disappear
Turning controller ON again:
- HID interfaces reappear
- Interface 1 immediately sends startup sequence


Conclusion:
HID interface presence alone is NOT a reliable controller
connection detector.
The reliable detector is communication activity on Interface 1.


------------------------------------------------------------
HID INTERFACE LIST
------------------------------------------------------------

When active, the dongle exposes:

Interface 0:
 Usage Page: 0x0001
 Usage:      0x0005

Interface 1:
 Usage Page: 0xFFA0
 Usage:      0x0001

Interface 2:
 Usage Page: 0x0001
 Usage:      0x0002

Interface 3:
 Usage Page: 0xFFEE
 Usage:      0x0000


------------------------------------------------------------
INTERFACE 1
------------------------------------------------------------

Main communication interface:

Interface:
- Number: 1
- Usage Page: 0xFFA0
- Usage: 0x0001


Detection logic:

1. Find Interface 1.
2. Open it.
3. Read reports.

Controller connected:
- Interface 1 produces data.

Controller disconnected:
- No Interface 1 traffic.
- Eventually HID interfaces may disappear.


Do NOT use:
- Interface existence alone
- Heartbeat timeout alone

as the primary connection detector.


------------------------------------------------------------
INTERFACE 1 PACKET FORMAT
------------------------------------------------------------

Reports:

Length:
- 32 bytes

Header:

Byte 0:
    0x5A

Byte 1:
    0xA5


Byte 2:
    Command / packet type


Last byte:
    Checksum / CRC


------------------------------------------------------------
STARTUP SEQUENCE
------------------------------------------------------------

When controller communication starts,
Interface 1 sends an initialization burst:

5A A5 01 ...
5A A5 A1 ...
5A A5 02 ...
5A A5 04 ...
5A A5 10 ...
5A A5 11 ...


Example:

5A A5 01 01 00 82 02 ...
5A A5 A1 01 00 02 41 ...
5A A5 02 01 00 FF FF ...
5A A5 04 01 00 14 20 ...
5A A5 10 01 00 01 ...
5A A5 11 01 00 01 ...


Likely meaning:

0x01:
- Device/controller information

0xA1:
- Controller state/capabilities

0x02:
- Status information

0x04:
- Configuration information

0x10:
- Heartbeat

0x11:
- Status/event response


------------------------------------------------------------
HEARTBEAT
------------------------------------------------------------

Packet:

5A A5 10 01 00 01 00 00 00 01 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 13


Frequency:
- Approximately every 30 seconds


Important:
Heartbeat is NOT suitable for disconnect detection.

Reason:
- Timeout would be very slow.
- Controller disconnect is visible earlier through
  Interface 1 communication stopping and/or HID removal.


------------------------------------------------------------
CURRENT MONITORING APPROACH
------------------------------------------------------------

Recommended logic:

1. Locate Interface 1.

2. Continuously read Interface 1.

3. First valid packet:
       CONTROLLER CONNECTED

4. While packets continue:
       Controller remains connected

5. When Interface 1 stops producing communication:
       Controller disconnected


The current script combines:
- HID enumeration
- Interface 1 reading
- Immediate disconnect detection