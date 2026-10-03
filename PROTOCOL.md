# Wearfit Pro (Bluetrum) watch — BLE protocol

Confirmed on Wearfit X10 (model code 5911, fw 1.13). Everything below was verified
against a live session and the companion app's own traffic log.

## 1. GATT services

| Service | Chars | Purpose |
|---|---|---|
| `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | `6e400002` write-wo-resp, `6e400003` notify | **Main command/data channel** |
| `6e400011-b5a3-f393-e0a9-e50e24dcca9e` | `6e400012` write-wo-resp, `6e400013` notify | File transfer (watchfaces, resources) |
| `0000ff12-0000-1000-8000-00805f9b34fb` | `ff13` write, `ff14` notify, `ff15` read+write-wo-resp | Bluetrum ZK FOTA (active only in OTA mode) |
| `0000fe59-0000-1000-8000-00805f9b34fb` | `8ec90001` write+notify, `8ec90002` read+write-wo-resp | Bluetrum "OTA fix" bootloader (Nordic-style DFU) |

No GAP/GATT (0x1800/0x1801) services exposed. No characteristic on the main channel is
readable; everything is write + notify.

**Critical:** notifications on `6e400003` are only received through
`AcquireNotify` (raw L2CAP socket). A normal `StartNotify` succeeds (CCCD accepted)
but data never arrives through the D-Bus properties path on BlueZ.

Link: LE bonding works; recommended flow is connect → `AcquireWrite` (negotiates MTU,
380 observed) → `AcquireNotify` → handshake.

## 2. Frame format

```
offset  size  field
0       1     magic: 0xAB (normal) or 0xEA (extended/auxiliary features)
1       2     length, big-endian: number of bytes AFTER this field (i.e. total-3)
3       1     flag: 0xFF (normal commands) or 0x00 (extended family)
4       1     class  (function group)
5       1     op     (function within group)
6..     n     payload
```

- `total = len + 3`
- No checksum, no crypto anywhere on this channel.
- Frames larger than the negotiated MTU-3 are split: continuation chunks are raw
  19-byte pieces prefixed by a 1-byte chunk index (see `OrderUtil.handleMessageBytes`
  semantics) — the device reassembles them.
- Incoming frames from the watch use the same format (0xAB or 0xEA).

## 3. Connection handshake

Sequence (timings from a real session):

```
[link up, services resolved, notify acquired]
  ~200ms after notify:
app -> watch  ab 00 17 ff e0 80 00 08 76 69 76 6f 31 39 30 34 09 <uid bytes>
              \class 0xE0 op 0x80: connect request
              payload: <type> <modelLen> <model ascii> <uidLen> <uid ascii>
              type: 0 = new device, 1 = already bound, 2 = disconnect (model forced to "o", uid "0")
              model: phone model string (e.g. "vivo1904"), up to 12 bytes
              uid:   logged-in account id as ascii

watch -> app  ab 00 04 ff e0 80 00                      (connect state: accepted)
app -> watch  ea 00 04 ff e3 01 00                      (BT dual-link status)
watch -> app  ab 00 06 ff 20 80 09 03 b5                (spontaneous pairing-state push)
app -> watch  ab 00 04 ff 92 80 01                      (get device info)
watch -> app  ab 00 11 ff 92 c0 01 0d 00 17 17 00 00 00 00 08 00 e2 00 80
watch -> app  ab 00 11 ff 9b 00 20 01 00 00 00 00 00 00 00 00 00 00 00
```

Decoding the `0x92` device-info frame (byte offsets include the 0xAB header):

| offset | meaning |
|---|---|
| 6, 7 | OTA version: `d[6] + d[7]/100` (e.g. `01 0d` → "1.13") |
| 8 | low code byte (used when 9/10 are zero) |
| 9, 10 | **model code**, big-endian: `d[9]*256 + d[10]` (0x17 0x17 → **5911**) |
| 11 | bit1 = licensed, bit2 = in-OTA-mode |
| 12 | bit0 = Alipay, bit4 = WeChat pay |
| 15 | bit0=step-length setting, bit1=sleep-time, bit2=12/24h, bit3=wechat-sport (all **inverted**), bit4=HR-warning, bit5=nordic-OTA-type, bit6=phone-serial-required, bit7=menstruation |
| 16 | health pack: 0 = BP ✓ + SpO2 ✓ (10=BP, 11=contHR, 12=ECG, 14=all, 15=contHR+SpO2, 16=SpO2) |
| 17 | bit0=pages-manager, bit1=Instagram, bit2=sedentary, bit3=HR-battery-save, bit4=IR-HR-sensor, bit5=extended-messages, bit6=weather, bit7=converse |
| 18 | screen type/resolution table entry (0 = unknown) |

The `0x9B` info2 frame: bytes 8..13 = equipment code (ASCII, may be NULs),
byte 14 = custom watchface background count, byte 15 = JS framework version
(0 = no JS engine → no mini-apps).

## 4. Command table (verified classes)

| Class | Op | Direction | Meaning |
|---|---|---|---|
| 0x92 | 0x80 0x01 | → watch | request device info |
| 0x92 | — | ← watch | device info (see table above) |
| 0x9B | — | ← watch | info2: equipment code, dial bg count, JS version |
| 0x93 | 0x80 | → watch | time sync: `AB 00 0B FF 93 80 00 <yearBE> <mon> <day> <hh> <mm> <ss>` |
| 0x91 | 0x80 | ← watch | time sync ack |
| 0x71 | 0x80 | → watch | find watch (rings + vibrates) |
| 0xE0 | 0x80 | → watch | connect request (see handshake) |
| 0xE0 | 0x80 | ← watch | connect state |
| 0x21 | 0x80 | ← watch | connect request ack |
| 0x20 | 0x80 | ← watch | spontaneous pairing-state push |
| 0xE3 | 0x01 | → watch | BT dual-link status (`EA 00 04 FF E3 01 00`) |
| 0x72 | — | ← watch | BT link status push (`EA 00 06 FF 72 01 01 01 00`) |
| 0x02 | 0x03 | ←→ | available memory query (`EA 00 05 00 02 03 <t> <t2>`) |
| 0x14 | 0x01 | ←→ | screen size (`EA 00 03 00 14 01` → `01 01 70 01 c0 01` = 368×448 LE u16s) |
| 0x31 | 0x80 | → watch | single/realtime measurement start |
| 0x51 | 0x20 | ← watch | **health data sync** (see §5) |
| 0xFE | 0x00 | → watch | diagnostics (sub-op: 1=crash dump, 2=power, 3=CPU/mem, 0x30=license) |
| 0x0B | 0x02 | ← watch | heartbeat (reply: `EA 00 03 00 0B 02`) |

## 5. Health data (class 0x51) — decoded from a live session

```
ab 00 16 ff 51 20 1a 0a 04 01 00 00 00 00 00 00 6c 63 92 5f 00 00 00 00 00
                 |op|  \_date_/  \_steps/cal_/  HR SpO2 SYS DIA  ...
```

- `0x20` = hourly-measurement sync op
- date bytes = day/month/(year)/hour of the sample
- then counters (steps, calories) and single-byte measurements:
  **HR = 0x6c = 108, SpO2 = 0x63 = 99, systolic = 0x92 = 146, diastolic = 0x5f = 95**,
  stress and other fields follow. Values verified against the app's decoded log
  ("心率:108 血氧:99 收缩压146 舒张压95 压力:68").

The watch measures on its own schedule (hourly) and pushes these frames after connect.

## 6. OTA — Bluetrum ABOta

Entry: command `EA 00 04 00 02 02 00` ("start ZK OTA") over the main channel →
watch reboots into OTA mode → the app reconnects and drives the FOTA service
(`FF12` write `FF15`, notify `FF14`), or the fix bootloader (`FE59`, chars
`8ec90001/8ec90002`).

Wire protocol of ABOta (from the official `com.bluetrum.fota` library embedded in
the companion app — no container, no signatures on the host side):

```
identification magic   CC AA 55 EE 12 19 E4
0x91 <seq> <type> ...              GET_INFO (type 1 = version, 2 = update[size:2,crc:4])
0x92 <seq> <TLVs>                  GET_INFO_ALL (TLV: 1=ver, 3=TWS, 4=status, 6=channel)
0xA0 <seq> <u32 addr> <u32 len> <data...>   START (first data chunk)
0x20 <seq> <chunk ≤512>            SEND_DATA
device -> host: 0x90 <state> (0x00 ok/next, 0xFF done, 0xFE continue, 0xFD pause,
                                 0x80 TWS-disconnect, other = device error code)
```

Recovery: a watch left in OTA mode without data usually reboots back after a
disconnect + timeout. The `FE59` "fix" service accepts the same protocol.

## 7. Gotchas

- **`AcquireNotify` is mandatory** for receiving notifications on BlueZ.
- The frame magic is `0xAB`, not `0xAA` — off-by-one here = total silence.
- Keep the phone app away: the watch serves one BLE client for the command channel.
- Firmware rejects `FF14` CCCD enable with ATT error 0x01 while not in OTA mode.
- The `0x9B` info2 frame arrives right after `0x92`, same trigger.

## 8. Tools

- `tools/channel.py` — connect + frame send/receive over AcquireNotify socket
- `tools/interrogate.py` — full device interrogation (info, screen, memory, …)
