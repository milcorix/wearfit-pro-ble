"""Рабочий BLE-клиент для часов Wearfit X10 (Bluetrum).

Использование:
    import channel
    ch = await channel.connect()      # подключение + AcquireNotify/AcquireWrite
    await ch.send(bytes)              # отправить фрейм
    ch.on_frame = lambda f: ...       # обработка входящих фреймов
    frames = ch.poll()                # забрать накопленные фреймы

Протокол: фрейм AB <len_hi> <len_lo> <FF|00> <class> <op> [payload]
Входящие фреймы часы шлют сами (спонтанный стейт-пуш) и в ответ на команды.
ВАЖНО: нотификации получаются только через AcquireNotify (socket fd),
обычный StartNotify на этих часах не доставляет данные.
"""
import asyncio
import os
import socket
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


def unwrap(v):
    while hasattr(v, "value"):
        v = v.value
    return v


def frame(*payload):
    """AB <len> FF <class> <op> <payload...> — len = байты после len-поля."""
    fr = bytearray([0xAB, 0x00, 0x00, 0xFF]) + bytes(payload)
    n = len(fr) - 3
    fr[1] = (n >> 8) & 0xFF
    fr[2] = n & 0xFF
    return bytes(fr)


def connect_request(connect_type=0, model="Linux", uid="0"):
    fr = bytearray([0xAB, 0x00, 0x00, 0xFF, 0xE0, 0x80, connect_type])
    m = model.encode()
    fr += bytes([len(m)]) + m
    u = uid.encode()
    fr += bytes([len(u)]) + u
    n = len(fr) - 3
    fr[1] = (n >> 8) & 0xFF
    fr[2] = n & 0xFF
    return bytes(fr)


class Channel:
    def __init__(self, bus, dev_path, wsock, notify_sock, mtu):
        self.bus = bus
        self.dev_path = dev_path
        self.wsock = wsock
        self.notify_sock = notify_sock
        self.mtu = mtu
        self.buffer = b""
        self.on_frame = None

    def poll(self):
        """Читает сокет, возвращает список полных фреймов (по заголовку AB/EA)."""
        out = []
        self.notify_sock.setblocking(False)
        try:
            data = self.notify_sock.recv(4096)
            if data:
                self.buffer += data
        except BlockingIOError:
            pass
        while len(self.buffer) >= 3:
            hdr = self.buffer[0]
            if hdr not in (0xAB, 0xEA):
                self.buffer = self.buffer[1:]
                continue
            ln = (self.buffer[1] << 8) | self.buffer[2]
            total = ln + 3  # ab + len(2) + payload(len байт после len-поля)
            if len(self.buffer) < total:
                break
            fr = self.buffer[:total]
            self.buffer = self.buffer[total:]
            out.append(fr)
            if self.on_frame:
                self.on_frame(fr)
        return out

    async def awrite(self, data: bytes):
        """Отправить фрейм (крупные фреймы режутся на куски по MTU-3)."""
        obj = self.bus.get_proxy_object("org.bluez", self.wx, Node.parse(CHAR_XML))
        c = obj.get_interface("org.bluez.GattCharacteristic1")
        maxc = self.mtu - 3
        for i in range(0, len(data), maxc):
            await c.call_write_value(data[i:i + maxc], {"type": Variant("s", "command")})

    def send(self, data: bytes):
        """Синхронная обёртка над awrite."""
        asyncio.get_event_loop().create_task(self.awrite(data))


async def connect():
    bus = MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True)
    await bus.connect()
    om = bus.get_proxy_object("org.bluez", "/", Node.parse(OM_XML))
    om_if = om.get_interface("org.freedesktop.DBus.ObjectManager")

    dev_path = None
    for _ in range(3):
        for p, d in (await om_if.call_get_managed_objects()).items():
            if "org.bluez.Device1" in d and unwrap(d["org.bluez.Device1"].get("Address")) == DEV_ADDR:
                dev_path = p
                break
        if dev_path:
            break
        await asyncio.sleep(1)
    if not dev_path:
        raise RuntimeError("часы не найдены — проверь, что они не заняты телефоном")

    dev = bus.get_proxy_object("org.bluez", dev_path, Node.parse(DEV_XML))
    props = dev.get_interface("org.freedesktop.DBus.Properties")
    try:
        if not unwrap(await props.call_get("org.bluez.Device1", "Connected")):
            await dev.get_interface("org.bluez.Device1").call_connect()
            await asyncio.sleep(2)
    except Exception as e:
        print("connect:", e)
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
    if not (wx and tx):
        raise RuntimeError("NUS-характеристики не найдены")

    wch = bus.get_proxy_object("org.bluez", wx, Node.parse(CHAR_XML)).get_interface("org.bluez.GattCharacteristic1")
    tch = bus.get_proxy_object("org.bluez", tx, Node.parse(CHAR_XML)).get_interface("org.bluez.GattCharacteristic1")

    wreply = await wch.call_acquire_write({})
    wfd, wmtu = wreply[0], wreply[1]
    nreply = await tch.call_acquire_notify({})
    nfd, nmtu = nreply[0], nreply[1]

    ch = Channel(bus, dev_path, socket.socket(fileno=os.dup(wfd)),
                 socket.socket(fileno=os.dup(nfd)), nmtu)
    ch.wx = wx
    return ch
