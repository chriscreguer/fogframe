# fogframe

A 13.3" Spectra-6 e-paper frame showing my [Fog of World](https://fogofworld.app/)
exploration, rebuilt a few times a day.

This repo holds **only the current rendered frame** — it is the URL the panel
fetches on power-up, nothing more. It is republished as a single commit each
time, so there is no history here.

- `device/frame.bin` — RAW T133A01 4bpp buffer (1200×1600, 2 px/byte, high
  nibble = even pixel; `0x0=W 0x2=G 0x6=R 0xB=Y 0xD=B 0xF=BK`)
- `device/preview.png` — human-viewable version of the same image

**Want to build one?** The full, configurable project lives at
[chriscreguer/fogframe-epaper](https://github.com/chriscreguer/fogframe-epaper) —
point it at your own bounding box and it renders your city.
