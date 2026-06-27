# fogframe

Turns my [Fog of World](https://fogofworld.app/) exploration data into a daily
image on a 13.3" Spectra-6 e-paper frame — regenerated entirely in the cloud, no
computer required.

```
 Phone (Fog of World) ──sync──▶ Dropbox
                                   │
        GitHub Actions (daily cron, runs on GitHub's servers)
          pull Sync ─▶ snapshot+discovery ─▶ render ─▶ quantise to 6 colours
                                   │
                         commit device/frame.bin
                                   │
   XIAO ESP32-S3 + EE02 board ──wake daily──▶ fetch frame.bin ─▶ paint ─▶ sleep
                                   │
                       13.3" Spectra-6 e-paper panel
```

## Pieces

| File | Job |
|------|-----|
| `parser.py` | Decode Fog of World sync tiles (from CaviarChen's parser) |
| `dropbox_pull.py` | Download the Sync folder via a Dropbox refresh token |
| `snapshot.py` | Maintain daily snapshots + the rolling 30-day discovery log |
| `render_fog.py` | Composite fog over the baked street base → 1200×1600 RGB |
| `pack_spectra6.py` | Quantise to the 6 Spectra colours → `device/frame.bin` (+ preview) |
| `build.py` | Run the whole pipeline (used by CI) |
| `.github/workflows/daily.yml` | The daily cloud job |
| `firmware/fogframe/` | XIAO ESP32-S3 firmware for the EE02 board |
| `assets/map_base.png` | Baked Mapbox street base (static; only the fog changes) |

`device/frame.bin` is the RAW T133A01 4bpp buffer (1200×1600, 2 px/byte,
high nibble = even pixel, nibble = panel colour code
`0x0=W 0x2=G 0x6=R 0xB=Y 0xD=B 0xF=BK`). The firmware streams it straight into
the Seeed_GFX sprite — no on-device decoding.

## Setup (one time)

### 1. GitHub Actions secrets
Repo → Settings → Secrets and variables → Actions → **New repository secret**, add:

| Name | Value |
|------|-------|
| `DROPBOX_APP_KEY` | the Dropbox app key |
| `DROPBOX_APP_SECRET` | the Dropbox app secret |
| `DROPBOX_REFRESH_TOKEN` | the long-lived refresh token |

(The refresh token was generated via the offline OAuth flow; it does not expire.)

### 2. Trigger a first run
Actions tab → **daily-frame** → *Run workflow*. It pulls your data, builds
`device/frame.bin`, and commits it. Check `device/preview.png` to see the result.

### 3. Flash the firmware
- Arduino IDE: install the **Seeed_GFX** library (remove TFT_eSPI if present — they conflict).
- Open `firmware/fogframe/fogframe.ino`.
- Board: **XIAO_ESP32S3**, and set **Tools → PSRAM: OPI PSRAM** (required — the
  frame buffer is 960 KB).
- Wi-Fi SSID/password and the image URL are at the top of the `.ino`.
- Upload. The panel refreshes (~25–35 s) and then sleeps for ~24 h.

## Updating the look
Tuning knobs live in `pack_spectra6.py` (`SAT_BOOST`, `SAT_THRESHOLD`, the
chromatic palette) and `render_fog.py` (`COLOR_FOG`, `FOG_OPACITY`, `BBOX_*`).
Re-run `python build.py --data "<path to local Fog of World folder>"` to preview
locally without touching Dropbox.

## Changing the map area / base style
The street base is baked once. To move/restyle it, regenerate `assets/map_base.png`
at 1200×1600 for the new bbox (the original used a Mapbox style via a headless
browser) and update `BBOX_*` in `render_fog.py` + `snapshot.py` to match.
