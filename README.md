# Wearfit Pro smartwatches (Bluetrum XunLong) — BLE reverse engineering

Reverse engineering of budget smartwatches that pair with the **Wearfit Pro** Android/iOS app
(`com.wakeup.howear`). Confirmed on **Wearfit X10** (`v.13YM0042-1_[fwk_1.11]_[sdk_1.11]_[app2.11]`,
model code **5911**, firmware **1.13**) and likely applicable to the whole family of
Apple-Watch-clone watches on this app: HK89, X8 Ultra, T800 Ultra, A9/A10 series, etc.
Main SoC platform: **Bluetrum 中科蓝讯 "XunLong"** series.

> **TL;DR:** the watch is fully controllable from a PC over BLE — handshake, time sync,
> find-watch (it really rings!), and the health data format (heart rate / SpO2 / blood
> pressure) is decoded. A working Python client is included. No crypto, no signatures.

## Why

The official app is ad-ridden, requires an account and a Chinese cloud for everything.
This project documents the protocol so you can build your own clean client, upload custom
watchfaces, or write your own firmware for the watch you own.

## What works today

- ✅ Full handshake from a PC (`tools/channel.py`)
- ✅ Commands execute: time sync, find-watch (rings+vibrates), settings
- ✅ Device info decode: firmware version, model code, capability bits
- ✅ Health data frame format decoded (HR / SpO2 / blood pressure / stress / steps)
- ✅ Dial (watchface) .bin samples collected; public CDN of dials found
- ⏳ Custom watchface packer (in progress)
- ⏳ Own Android client (protocol proven, implementation next)

## Docs

| Doc | Content |
|---|---|
| [PROTOCOL.md](PROTOCOL.md) | GATT services, frame format, handshake, command table, health data, OTA |
| [HARDWARE.md](HARDWARE.md) | Confirmed hardware boundaries & capability bits |
| [README.ru.md](README.ru.md) | Русская версия |

## Quick start

Requirements: Linux with BlueZ, Python 3.10+, [`dbus-fast`](https://pypi.org/project/dbus-fast/).

```bash
pip install dbus-fast
python tools/interrogate.py   # connect, handshake, ask the watch everything it answers
```

The watch must not be held by your phone (its BLE stack serves one client at a time).

## Key findings (short version)

1. Command frames start with **`0xAB`** (extended family `0xEA`) — not `0xAA` as it may appear
   from quick hexing.
2. Responses are delivered **only if you subscribe via `AcquireNotify`** (raw socket).
   BlueZ `StartNotify` succeeds but silently never delivers data on these watches.
3. Frame length field = number of bytes after the length field; **total = len + 3**.
4. Handshake carries the phone model and the logged-in user id; the watch replies with
   firmware version, model code and capability bits.
5. Health data sync uses class `0x51`; heart rate, SpO2, systolic/diastolic BP are plain bytes.
6. OTA (Bluetrum ABOta) pushes a raw `.bin` — no container, no signatures on the app side.

See [PROTOCOL.md](PROTOCOL.md) for all of it with byte-level detail.

## Hardware boundaries (X10)

| Present | Absent |
|---|---|
| Screen 368×448, speaker, vibro | WiFi, GPS chip, NFC (unconfirmed), |
| HR sensor (with IR mode), SpO2, calc BP | body temperature, ECG |
| Accelerometer, BT-classic calls (HFP) | JS engine (no mini-apps), internet |

Capability bits decoded from the handshake — see [HARDWARE.md](HARDWARE.md).

## Disclaimer

Educational purposes, for devices you own. Interoperability documentation only —
no proprietary code from the vendor app is included or distributed. Flashing firmware
can brick your watch; the official app remains the safe path for warranty behavior.

## License

[MIT](LICENSE)
