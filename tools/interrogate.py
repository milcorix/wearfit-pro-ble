import asyncio
import os
import socket
import time
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType
from dbus_fast.introspection import Node
from dbus_fast import Variant

DEV_ADDR = "41:42:65:1E:A9:84"
OM_XML = """<node><interface name="org.freedesktop.DBus.ObjectManager"><method name="GetManagedObjects"><arg name="obj" type="a{oa{sa{sv}}}" direction="out"/></method></interface></node>"""
DEV_XML = """<node><interface name="org.bluez.Device1"><method name="Connect"/><method name="Disconnect"/></interface>
<interface name="org.freedesktop.DBus.Properties"><method name="Get"><arg name="interface" type="s" direction="in"/><arg name="name" type="s" direction="in"/><arg name="value" type="v" direction="out"/></method></interface></node>"""
CHAR_XML = """<node><interface name="org.bluez.GattCharacteristic1">
<method name="WriteValue"><arg name="value" type="ay" direction="in"/><arg name="options" type="a{sv}" direction="in"/></method>
<method name="AcquireNotify"><arg name="options" type="a{sv}" direction="in"/><arg name="fd" type="h" direction="out"/><arg name="mtu" type="q" direction="out"/></method>
<method name="AcquireWrite"><arg name="options" type="a{sv}" direction="in"/><arg name="fd" type="h" direction="out"/><arg name="mtu" type="q" direction="out"/></method>
</interface></node>"""

CLASSES = {
    0x20: "pairing-state(спонтанный)", 0x21: "connectReq-ack", 0x92: "DEVICE_INFO",
    0x9B: "DEVICE_INFO2(equipmentCode)", 0xAA: "SN-ответ?", 0xE0: "connectState",
    0xCB: "license", 0x91: "timeSync-ack", 0xA0: "OTA-info", 0xC7: "undef",
}

def unwrap(v):
    while hasattr(v, "value"):
        v = v.value
    return v


def decode(frame):
    if len(frame) < 6:
        return ""
    cls = frame[4]
    name = CLASSES.get(cls, f"class=0x{cls:02x}")
    extra = ""
    if cls == 0x92 and len(frame) >= 18:
        ver = f"{frame[6]}.{frame[7]:02d}"
        code = frame[9] * 256 + frame[10]
        extra = f" | fw={ver} code={code} caps={frame[11:18].hex(' ')}"
    if cls == 0x9B and len(frame) > 14:
        eq = frame[8:14].decode("utf-8", "replace")
        extra = f" | equipmentCode={eq!r} watchfaceBgNum={frame[14] if len(frame)>14 else '?'} jsVer={frame[15] if len(frame)>15 else '?'}"
    return name + extra


async def main():
    bus = MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True)
    await bus.connect()
    om = bus.get_proxy_object("org.bluez", "/", Node.parse(OM_XML))
    om_if = om.get_interface("org.freedesktop.DBus.ObjectManager")

    dev_path = None
    for p, d in (await om_if.call_get_managed_objects()).items():
        if "org.bluez.Device1" in d and unwrap(d["org.bluez.Device1"].get("Address")) == DEV_ADDR:
            dev_path = p
            break
    if not dev_path:
        print("NOT_FOUND")
        return
    dev = bus.get_proxy_object("org.bluez", dev_path, Node.parse(DEV_XML))
    props = dev.get_interface("org.freedesktop.DBus.Properties")
    try:
        if not unwrap(await props.call_get("org.bluez.Device1", "Connected")):
            await dev.get_interface("org.bluez.Device1").call_connect()
            await asyncio.sleep(2)
    except Exception as e:
        print("connect:", e)
        return
    for _ in range(60):
        try:
            if unwrap(await props.call_get("org.bluez.Device1", "ServicesResolved")):
                break
        except Exception:
            pass
        await asyncio.sleep(0.25)

    mo = await om_if.call_get_managed_objects()
    wx = tx = None
    for p, d in mo.items():
        if "org.bluez.GattCharacteristic1" not in d:
            continue
        u = unwrap(d["org.bluez.GattCharacteristic1"]["UUID"]).lower()
        if u.startswith("6e400002"):
            wx = p
        elif u.startswith("6e400003"):
            tx = p
    wch = bus.get_proxy_object("org.bluez", wx, Node.parse(CHAR_XML)).get_interface("org.bluez.GattCharacteristic1")
    tch = bus.get_proxy_object("org.bluez", tx, Node.parse(CHAR_XML)).get_interface("org.bluez.GattCharacteristic1")

    nreply = await tch.call_acquire_notify({})
    nsock = socket.socket(fileno=os.dup(nreply[0]))
    mtu = nreply[1]
    print(f"notify socket ok, mtu={mtu}")

    buf = bytearray(b"")
    t0 = time.time()

    def drain(dur=0.0):
        nonlocal buf
        end = time.time() + dur
        while time.time() < end:
            nsock.setblocking(False)
            try:
                data = nsock.recv(4096)
                if data:
                    buf.extend(data)
            except BlockingIOError:
                pass
            time.sleep(0.05)
        out = []
        while len(buf) >= 3:
            hdr = buf[0]
            if hdr not in (0xAB, 0xEA):
                buf = buf[1:]
                continue
            ln = (buf[1] << 8) | buf[2]
            total = ln + 3
            if len(buf) < total:
                break
            fr = bytes(buf[:total])
            del buf[:total]
            out.append(fr)
        return out

    async def ask(name, fr, wait=1.5):
        await wch.call_write_value(fr, {"type": Variant("s", "command")})
        print(f">> {name}: {fr.hex(' ')}")
        for f in drain(wait):
            print(f"   << {f.hex(' ')}  [{decode(f)}]")

    print("=== ДОПРОС ЧАСОВ ===")
    cr = bytearray([0xAB, 0, 0, 0xFF, 0xE0, 0x80, 0x00, 0x05]) + b"Linux" + bytes([0x01]) + b"0"
    n = len(cr) - 3
    cr[1] = (n >> 8) & 0xFF
    cr[2] = n & 0xFF
    await ask("handshake", bytes(cr), 2.5)
    await ask("devInfo", bytes([0xAB, 0x00, 0x04, 0xFF, 0x92, 0x80, 0x01]), 2.5)
    await ask("getDeviceSN", bytes([0xAB, 0x00, 0x03, 0xFF, 0xAA, 0x80]), 2)
    await ask("getScreen", bytes([0xEA, 0x00, 0x03, 0x00, 0x14, 0x01]), 2)
    await ask("getAvailableMemory", bytes([0xEA, 0x00, 0x05, 0x00, 0x02, 0x03, 0x00, 0x00]), 2)
    await ask("getPowerConsumption", bytes([0xEA, 0x00, 0x03, 0xFE, 0x00, 0x02]), 2)
    await ask("getCpuUsed", bytes([0xEA, 0x00, 0x03, 0xFE, 0x00, 0x03]), 2)
    await ask("getCrashData", bytes([0xEA, 0x00, 0x03, 0xFE, 0x00, 0x01]), 2)
    await ask("getWifiState", bytes([0xEA, 0x00, 0x03, 0x00, 0x33, 0x03]), 2)
    await ask("getMtu", bytes([0xAB, 0x00, 0x04, 0xFF, 0xA7, 0x80, 0x01]), 2)
    await ask("getLicenseNum", bytes([0xAB, 0x00, 0x02, 0xFF, 0xCB]), 2)
    await ask("getDeviceFN", bytes([0xEA, 0x00, 0x03, 0xFF, 0xAA, 0x01]), 2)
    await ask("requestDeviceLicense", bytes([0xEA, 0x00, 0x03, 0xFE, 0x00, 0x30]), 2)
    # devInfo повторно — info2 приходит после info
    await ask("devInfo(повтор)", bytes([0xAB, 0x00, 0x04, 0xFF, 0x92, 0x80, 0x01]), 3)

    print("=== финальный сбор 10 s ===")
    for f in drain(10):
        print(f"   << {f.hex(' ')}  [{decode(f)}]")

    t = time.strftime("%Y%m%d_%H%M%S")
    with open(f"/home/alex/Документы/прошивка на часы/interrogation_{t}.log", "w") as f:
        f.write(f"mtu={mtu}\n")
    print("DONE")


asyncio.run(main())
