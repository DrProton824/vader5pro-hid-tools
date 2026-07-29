"""
tools/vendor_init_trigger.py — Vader 5 Pro vendor HID initialization trigger.

Waits for the vendor HID interface, sends the recovered initialization
sequence on user confirmation, then sends the stop command and exits.
"""


import hid
import time

VID = 0x37D7
PID = 0x2401
USAGE_PAGE = 0xFFA0

INIT = [
    [0x5A,0xA5,0x01,0x02,0x03],
    [0x5A,0xA5,0xA1,0x02,0xA3],
    [0x5A,0xA5,0x02,0x02,0x04],
    [0x5A,0xA5,0x04,0x02,0x06],
    [0x5A,0xA5,0x11,0x07,0xFF,0x01,0xFF,0xFF,0xFF,0x15],
]

STOP = [0x5A,0xA5,0x11,0x07,0xFF,0x00,0xFF,0xFF,0xFF,0x14]


def find_interface():
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == USAGE_PAGE:
            return d["path"]
    return None


def send(dev, data):
    dev.write([0x00] + data + [0] * (32 - len(data)))


path = find_interface()

while path is None:
    input("Interface 1 not found. Connect controller, then press ENTER...")
    path = find_interface()

dev = hid.device()
dev.open_path(path)

print("Interface 1 found.")
input("Press ENTER to send initialization sequence...")
print("Sending initialization sequence...")

for cmd in INIT:
    send(dev, cmd)
    time.sleep(0.05)

print("Handshake complete.")

input("Press ENTER to send stop command...")
print("Sending stop command...")
send(dev, STOP)

print("Waiting 5 seconds...")
time.sleep(5)
dev.close()
print("Closed.")
