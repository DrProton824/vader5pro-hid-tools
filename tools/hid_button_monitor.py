# Monitors Vader 5 Pro button input reports from the vendor HID channel
# (VID 0x37D7 / PID 0x2401, Usage Page 0xFFA0) using hidapitester.exe.
# Requires hidapitester.exe to be available in the script directory and decodes
# discovered HID bit fields into button press/release events.


import subprocess
import re
import time
import signal
import sys

# Vader 5 Pro discovered mappings
# Format: byte position : bit mask : button name

BUTTON_BITS = {
    11: {
        0x80: "X",
        0x40: "Select",
        0x20: "B",
        0x10: "A",
        0x08: "DPad Left",
        0x04: "DPad Down",
        0x02: "DPad Right",
        0x01: "DPad Up",
    },

    12: {
        0x80: "STICK-R",
        0x40: "STICK-L",
        0x20: "RT",
        0x10: "LT",
        0x08: "RB",
        0x04: "LB",
        0x02: "Start",
        0x01: "Y",
    },

    13: {
        0x80: "RM",
        0x40: "LM",
        0x20: "M4",
        0x10: "M3",
        0x08: "M2",
        0x04: "M1",
        0x02: "Z",
        0x01: "C",
    },

    14: {
        0x08: "Home",
        0x01: "Circle",
        0x02: "Arrow",
    }
}


def parse_report(line):
    """
    Extract HID hex reports from hidapitester output
    """
    if not line.startswith(" "):
        return None

    data = re.findall(r"[0-9A-Fa-f]{2}", line)

    if len(data) < 14:
        return None

    return [int(x, 16) for x in data]


def decode_buttons(report):
    """
    Convert HID report into pressed button set
    """
    pressed = set()

    for byte, mappings in BUTTON_BITS.items():
        value = report[byte]

        for mask, name in mappings.items():
            if value & mask:
                pressed.add(name)

    return pressed


def main():

    print("Starting Vader 5 Pro button monitor...")
    print()
    print("Press buttons. Ctrl+C exits.")
    print()

    cmd = [
        ".\\hidapitester.exe",
        "--vidpid",
        "37D7:2401",
        "--usagePage",
        "0xFFA0",
        "--open",
        "--length",
        "32",
        "--read-input-forever"
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    previous = set()

    try:
        for line in process.stdout:

            report = parse_report(line)

            if report is None:
                continue

            current = decode_buttons(report)

            pressed = current - previous
            released = previous - current

            for button in pressed:
                print(f"PRESS   {button}")

            for button in released:
                print(f"RELEASE {button}")

            previous = current

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        process.kill()


if __name__ == "__main__":
    main()
