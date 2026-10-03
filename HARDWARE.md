# Hardware boundaries — Wearfit X10 (code 5911)

Everything below was confirmed by live BLE interrogation (the watch answers protocol
queries), the capability-bit decoders inside the companion app, and a real sync session.

## Confirmed present

| Component | Details |
|---|---|
| Screen | **368 × 448**, portrait (query class 0x14 → `70 01 c0 01` LE u16s) |
| Speaker + vibration motor | find-watch command rings and vibrates |
| Heart-rate sensor | with **IR mode** (byte17 bit4) — continuous measurement |
| SpO2 sensor | byte16 = 0 → blood oxygen ✓ |
| "Blood pressure" | calculated (systolic/diastolic in health frames — verified 146/95) |
| Accelerometer | steps / sleep / sport modes |
| BT classic | calls (HFP) work with no app connected |
| Flash | dial/resource storage, health history; file transfer channel works |

## Confirmed absent

| Feature | Evidence |
|---|---|
| WiFi | `getWifiState` — no response; platform command only |
| GPS chip | protocol only forwards phone location |
| NFC | Alipay/WeChat-pay bits = 0; unconfirmed but unlikely |
| Body temperature | info2Byte5 = 0 → bodyTemp=false |
| ECG | byte16: ECG only for values 12/14 |
| JS engine | info2 byte15 (jsVer) = 0 → no mini-apps |
| Internet | everything comes through the phone over BLE |

## Capability bytes (from the handshake device-info frame)

Frame: `ab 00 11 ff 92 c0 01 0d 00 17 17 00 00 00 00 08 00 e2 00 80`

| byte | value | decoded |
|---|---|---|
| 11 | 0x00 | not licensed, not in OTA mode |
| 12 | 0x00 | no Alipay / WeChat pay |
| 15 | 0x08 | step-length ✓ sleep-time ✓ 12/24h ✓ (inverted bits); WeChat-sport ✗, HR-warning ✗, nordic=0 → **Bluetrum OTA**, phone-serial ✗, menstruation ✗ |
| 16 | 0x00 | **BP ✓ SpO2 ✓**, ECG ✗ |
| 17 | 0xE2 | Instagram ✓, sedentary ✓, **IR-HR ✓**, extended-messages ✓, weather ✓; pages-manager ✗, HR-battery-save ✗ |
| 18 | 0x00 | screen table entry unknown (measured directly: 368×448) |
| info2 byte5 | 0x00 | body-temperature ✗, immunity ✗ |
| info2 byte15 | 0x00 | **no JS engine** |
| info2 byte14 | 0x00 | custom watchface background count = 0 |

## Implications for custom firmware

- Target framebuffer: 368×448.
- Don't bother with: WiFi, GPS, NFC, body temperature, ECG, JS runtime.
- Must have: BLE GATT (4 services), AB/EA frame parser + command handlers, dial renderer,
  HR (IR)/SpO2/accelerometer drivers, HFP calls, vibro/speaker, storage, dual-bank OTA.
- OTA is the recovery path: raw .bin over Bluetrum FOTA, no signatures —
  but also no read-back, so keep a stock dump if you can get one.
