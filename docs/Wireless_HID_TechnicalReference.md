================================================================================
FLYDIGI VADER 5 PRO - TECHNICAL REFERENCE
================================================================================

DEVICES OVERVIEW
----------------
Three separate USB devices exist in this setup:

  1. Wireless Dongle        VID 0x37D7  PID 0x2401  ← PRIMARY
  2. Charging Dock          VID 0x1E7D  PID 0x2C92
  3. Dock Accessory         VID 0x37D7  PID 0x6001


COMMUNICATION MODEL
-------------------
PC
 |
 +-- VID 0x37D7 / PID 0x2401 (wireless dongle)
 |      |
 |      +-- wireless link
 |            |
 |            +-- Vader 5 Pro controller
 |
 +-- VID 0x1E7D / PID 0x2C92 (charging dock)
 |
 +-- VID 0x37D7 / PID 0x6001 (dock accessory interface)


================================================================================
1. WIRELESS DONGLE / RECEIVER                                         [PRIMARY]
================================================================================
VID:              0x37D7
PID:              0x2401
Windows Path:     USB\VID_37D7&PID_2401\FLYDIGI_VADER_5_PRO

Notes:
- Exists when dongle is plugged in, regardless of controller power state
- Controller does NOT appear as a separate USB/HID device
- Controller connection is handled internally by the dongle
- All controller communication goes through this device

INTERFACES
----------
Interface 0 (MI_00):  Xbox 360 Controller (XnaComposite)
  Usage Page:         0x0001 (Generic Desktop)
  Usage:              0x0005 (Game Pad)
  Windows Class:      XnaComposite
  Function:           XInput gamepad emulation

Interface 1 (MI_01):  Vendor HID - WIRELESS DATA CHANNEL            [MONITOR]
  Usage Page:         0xFFA0 (Vendor-defined)
  Usage:              0x0001
  Function:           Primary wireless communication channel
  Detection:          Data present  = Controller connected
                      No data       = Controller not connected

Interface 2 (MI_02):  HID Mouse
  Usage Page:         0x0001 (Generic Desktop)
  Usage:              0x0002 (Mouse)
  Function:           Mouse emulation

Interface 3 (MI_03):  Vendor HID - Secondary
  Usage Page:         0xFFEE (Vendor-defined)
  Usage:              0x0000
  Function:           Secondary vendor channel / unknown purpose

PYTHON ACCESS
-------------
hid.enumerate(0x37D7, 0x2401)   # Returns all 4 interfaces
Filter for Interface 1:
  interface['interface_number'] == 1
  interface['usage_page']       == 0xFFA0


================================================================================
2. CHARGING DOCK                                                   [NOT PRIMARY]
================================================================================
VID:              0x1E7D
PID:              0x2C92
Windows Path:     USB\VID_1E7D&PID_2C92

Notes:
- Separate USB device from the wireless dongle
- Not part of controller communication path
- Unrelated to detection logic

Interfaces exposed:
  - Mouse HID interface
  - Keyboard HID interface
  - Consumer control HID interface
  - System controller HID interface
  - Vendor-defined HID interface


================================================================================
3. DOCK / VENDOR ACCESSORY INTERFACE                               [NOT PRIMARY]
================================================================================
VID:              0x37D7
PID:              0x6001
Windows Path:     USB\VID_37D7&PID_6001\0123456789

Notes:
- Appears when dock/accessory is connected
- Separate from the wireless dongle
- Unrelated to controller HID communication


================================================================================
4. WIRELESS CONTROLLER                                             [NOT DIRECT]
================================================================================
VID/PID:          Unknown (not exposed)
Windows Path:     Not exposed before handshake

Notes:
- Controller power-on does NOT create a new HID device
- Controller does NOT appear in Get-PnpDevice output
- Controller connection is handled internally by the wireless dongle
- Vendor handshake required before controller HID reports appear
- Completely invisible to Windows device enumeration


================================================================================
PACKET PROTOCOL (Interface 1 / MI_01)
================================================================================
Header:           5A A5 [TYPE] 01 00 [DATA...]
Common Types:     0x01, 0x02, 0x04, 0x10, 0x11, 0xA1, 0xA6, 0xA8

Observed connection sequences:
  0x01 → 0x02                   (Most common, 3x observed)
  0xA1 → 0x04 → 0x10 → 0x11   (Full handshake, 2x observed)

Timing:           Packets sent in bursts, 1-30 second intervals (heartbeat)
Data:             Identical packets observed across multiple connections
                  Some bytes vary (battery, firmware state, counter)


================================================================================
CONTROLLER CONNECTION DETECTION
================================================================================
Method:           Monitor Interface 1 (MI_01) for data presence
Signal:           ANY data on Interface 1 = Controller wirelessly connected
                  NO data on Interface 1  = Controller not connected

Important:        Dongle connection alone produces NO data on Interface 1
                  Data only appears when controller is powered on and paired

Windows PnP:      Unreliable for detection - all devices remain in registry
                  regardless of actual connection state. Do not use.

================================================================================