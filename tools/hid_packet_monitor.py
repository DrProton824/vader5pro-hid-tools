# HID interface listener for capturing and logging raw reports from the selected
# VID 0x37D7 / PID 0x2401 device interface. Allows manual interface selection,
# continuously monitors HID reports, and saves timestamped hexadecimal packet logs.


import hid
import time
from datetime import datetime

VID = 0x37D7
PID = 0x2401


def choose_interface():
    missing_reported = False

    while True:
        devices = sorted(
            hid.enumerate(VID, PID),
            key=lambda d: d["interface_number"]
        )

        if not devices:
            if not missing_reported:
                print(
                    f"No HID interfaces found for VID {VID:04X}, PID {PID:04X}. Waiting..."
                )
                missing_reported = True

            time.sleep(1)
            continue

        missing_reported = False

        print("Available HID interfaces:\n")

        for device in devices:
            print(
                f"  [{device['interface_number']}] "
                f"Interface {device['interface_number']} | "
                f"Usage Page 0x{device['usage_page']:04X} | "
                f"Usage 0x{device['usage']:04X}"
            )

        while True:
            try:
                selection = int(input("\nSelect interface to watch: "))

                for device in devices:
                    if device["interface_number"] == selection:
                        selected = device

                        suffix = (
                            f"MI_{selected['interface_number']:02d}"
                            f"_UP_{selected['usage_page']:04X}"
                            f"_U_{selected['usage']:04X}"
                        )

                        return selected, f"hidlistener_{suffix}.txt"

            except ValueError:
                pass

            print("Invalid selection. Try again.")


selected, LOG_FILE = choose_interface()

IFACE = selected["interface_number"]
USAGE_PAGE = selected["usage_page"]
USAGE = selected["usage"]


def find():
    for device in hid.enumerate(VID, PID):
        if (
            device["interface_number"] == IFACE
            and device["usage_page"] == USAGE_PAGE
            and device["usage"] == USAGE
        ):
            return device["path"]

    return None


def log(data):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] " + " ".join(f"{byte:02X}" for byte in data)

    print(line)

    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(line + "\n")


with open(LOG_FILE, "w", encoding="utf-8") as file:
    file.write(f"=== hidlistener Started {datetime.now()} ===\n")
    file.write(f"VID:             0x{VID:04X}\n")
    file.write(f"PID:             0x{PID:04X}\n")
    file.write(f"Interface:       {IFACE}\n")
    file.write(f"Usage Page:      0x{USAGE_PAGE:04X}\n")
    file.write(f"Usage:           0x{USAGE:04X}\n\n")


print(
    f"\nWatching Interface {IFACE}, "
    f"Usage Page 0x{USAGE_PAGE:04X}, "
    f"Usage 0x{USAGE:04X}"
)
print(f"Log file: {LOG_FILE}\n")


path = find()

while True:
    try:
        if not path:
            path = find()

            if not path:
                time.sleep(0.1)
                continue

        # Open -> read once -> close immediately.
        device = hid.device()
        device.open_path(path)
        device.set_nonblocking(True)

        data = device.read(64)

        device.close()

        if data:
            log(data)

    except Exception:
        path = None
        time.sleep(0.1)
