# Monitors the FLYDIGI Vader 5 Pro wireless controller connection through
# the VID 0x37D7 / PID 0x2401 receiver and Interface 1 (Usage Page 0xFFA0).
# Detects controller connection/disconnection by monitoring HID communication
# and prints all received Interface 1 reports in hexadecimal format.


import hid
import time

VID = 0x37D7
PID = 0x2401

print("Monitoring controller connection...")

connected = False
h = None


def find_interface():
    for i in hid.enumerate(VID, PID):
        if i['interface_number'] == 1 and i['usage_page'] == 0xFFA0:
            return i

    return None


while True:
    try:
        # Check if Interface 1 exists
        iface = find_interface()

        # Interface disappeared = controller disconnected
        if not iface:
            if connected:
                print("✗ CONTROLLER DISCONNECTED")
                connected = False

            if h:
                try:
                    h.close()
                except:
                    pass

                h = None

            time.sleep(0.1)
            continue


        # Interface appeared = controller connected
        if not connected:
            print("✓ CONTROLLER CONNECTED")
            connected = True

            # YOUR HANDSHAKE HERE


        # Open interface if not already open
        if h is None:
            h = hid.device()
            h.open_path(iface['path'])
            h.set_nonblocking(True)


        # Quick read
        data = h.read(64, timeout_ms=100)

        if data:
            print(" ".join(f"{x:02X}" for x in data))


        time.sleep(0.5)


    except Exception:
        # Device disappeared while reading
        if connected:
            print("✗ CONTROLLER DISCONNECTED")

        connected = False

        if h:
            try:
                h.close()
            except:
                pass

        h = None

        time.sleep(0.5)
