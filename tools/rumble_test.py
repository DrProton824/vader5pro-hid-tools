"""
Vader 5 Pro - Test recovered 0x12 rumble command with intensity control.
"""

import hid
import time

VID = 0x37D7
PID = 0x2401
USAGE_PAGE = 0xFFA0


def find_interface():
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == USAGE_PAGE:
            return d["path"]
    return None


def transact(dev, data):
    packet = [0x00] + data
    packet += [0] * (33 - len(packet))   # Report ID + 32-byte report

    print(">", bytes(packet[1:]).hex())
    dev.write(packet)

    try:
        reply = dev.read(32, 200)
        if reply:
            print("<", bytes(reply).hex())
        else:
            print("< (timeout)")
    except Exception as e:
        print("< read failed:", e)


path = find_interface()

if path is None:
    raise RuntimeError("Vendor HID interface (usage page 0xFFA0) not found.")

dev = hid.device()
dev.open_path(path)

print("Connected.")

# Ask for intensity
while True:
    try:
        intensity = int(input("Set rumble intensity (0-100%): "))
        if 0 <= intensity <= 100:
            break
        print("Enter a value between 0 and 100.")
    except ValueError:
        print("Enter a number.")

strength = int(255 * intensity / 100)

print(f"Using intensity: {intensity}% ({strength:02X})")

RUMBLE_ON = [
    0x5A, 0xA5,
    0x12,
    0x06,
    strength, strength,
    0x00, 0x00, 0x00, 0x00
]

RUMBLE_OFF = [
    0x5A, 0xA5,
    0x12,
    0x06,
    0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
]

# Start immediately after entering intensity
print("Sending rumble ON...")
transact(dev, RUMBLE_ON)

input("Rumble active. Press ENTER to send rumble OFF...")

print("Sending rumble OFF...")
transact(dev, RUMBLE_OFF)

print("Finished. Device remains open.")
input("Press ENTER to close...")

dev.close()
print("Closed.")
