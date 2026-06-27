#!/usr/bin/env python3
"""
render_fog.py — render Fog of World data to a 1200x1600 RGB image.

Composites (draw order):
  1. Baked street base map (assets/map_base.png)
  2. Dark fog overlay over UNEXPLORED areas
  3. Red tint over areas first explored in the last 30 days (discovery log)

Geometry (BBOX + world projection) is identical to snapshot.py so the
discovery-log array stays pixel-aligned with the world array.

Usage:
    python render_fog.py <fow_data_dir> [out.png]
        fow_data_dir : folder containing a "Sync" subfolder
        out.png      : output path (default: build/fog_rgb.png)
"""
import os
import sys
import math
import logging
import contextlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
with contextlib.redirect_stdout(open(os.devnull, "w")):
    import parser as fow

# --- Configuration (BBOX must match snapshot.py) ---------------------------
BBOX_N, BBOX_S, BBOX_W, BBOX_E = 41.965, 41.870, -87.708, -87.603
CANVAS_W, CANVAS_H = 1200, 1600

BASE_MAP_PATH      = HERE / "assets" / "map_base.png"
DISCOVERY_LOG_PATH = HERE / "snapshots" / "discovery_log.npz"

COLOR_FOG    = (70, 70, 70)    # NEUTRAL gray overlay for unexplored (no blue cast)
FOG_OPACITY  = 0.55
COLOR_RECENT = (210, 35, 35)   # last-30-day exploration tint

SSAA, SSAA_THRESH = 4, 20
RECENT_DAYS = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("render_fog")

WORLD_RES = fow.MAP_WIDTH * fow.TILE_WIDTH * fow.BITMAP_WIDTH  # 4,194,304


def _lng_to_wx(lng):
    return (lng + 180.0) / 360.0 * WORLD_RES


def _lat_to_wy(lat):
    return (math.pi - math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))) \
           / (2.0 * math.pi) * WORLD_RES


def _expand_to_aspect(x0, x1, y0, y1, tw, th):
    w, h = x1 - x0, y1 - y0
    if w / h < tw / th:
        cx = (x0 + x1) / 2.0
        hw = h * tw / th / 2.0
        x0, x1 = cx - hw, cx + hw
    else:
        cy = (y0 + y1) / 2.0
        hh = w * th / tw / 2.0
        y0, y1 = cy - hh, cy + hh
    return x0, x1, y0, y1


def _bbox_world():
    x0, x1 = _lng_to_wx(BBOX_W), _lng_to_wx(BBOX_E)
    y0, y1 = _lat_to_wy(BBOX_N), _lat_to_wy(BBOX_S)
    return _expand_to_aspect(x0, x1, y0, y1, CANVAS_W, CANVAS_H)


def build_world_array(data_dir):
    """Parse FoW sync data → binary (H×W uint8) world array for the bbox."""
    x0, x1, y0, y1 = _bbox_world()
    W, H = int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0))
    world = np.zeros((H, W), dtype=np.uint8)
    bw = fow.BITMAP_WIDTH

    with contextlib.redirect_stdout(open(os.devnull, "w")):
        fog = fow.FogMap(data_dir)

    for tile in fog.tile_map.values():
        tile_wx = tile.x * fow.TILE_WIDTH * bw
        tile_wy = tile.y * fow.TILE_WIDTH * bw
        for (bx, by), block in tile.blocks.items():
            dx = int(tile_wx + bx * bw - x0)
            dy = int(tile_wy + by * bw - y0)
            if dx + bw <= 0 or dy + bw <= 0 or dx >= W or dy >= H:
                continue
            raw = np.frombuffer(block.bitmap, dtype=np.uint8).reshape(bw, bw // 8)
            bits = np.unpackbits(raw, axis=1)
            sy0 = max(0, -dy); sy1 = min(bw, H - max(0, dy) + sy0)
            sx0 = max(0, -dx); sx1 = min(bw, W - max(0, dx) + sx0)
            if sy1 > sy0 and sx1 > sx0:
                h, w = sy1 - sy0, sx1 - sx0
                world[max(0, dy):max(0, dy) + h, max(0, dx):max(0, dx) + w] |= bits[sy0:sy1, sx0:sx1]

    log.info(f"World array: {W}×{H} — {int(world.sum()):,} explored px")
    return world


def _ssaa(arr):
    """Anti-aliased upscale of a binary mask to canvas size, float 0..1."""
    pil = Image.fromarray(arr * 255, mode="L")
    pil_4x = pil.resize((CANVAS_W * SSAA, CANVAS_H * SSAA), Image.LANCZOS)
    pil_bin = Image.fromarray((np.array(pil_4x) > SSAA_THRESH).astype(np.uint8) * 255, mode="L")
    pil_canvas = pil_bin.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
    return np.array(pil_canvas).astype(np.float32) / 255.0


def _load_recent_mask(world_shape):
    """Return SSAA'd float mask (0..1) of pixels first explored in last 30d, or None."""
    if not DISCOVERY_LOG_PATH.exists():
        log.info("No discovery log — skipping red layer")
        return None
    disc = np.load(DISCOVERY_LOG_PATH)["log"]
    if disc.shape != world_shape:
        log.warning(f"Discovery log shape {disc.shape} ≠ world {world_shape} — skipping red layer")
        return None
    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).toordinal()
    recent = ((disc > 0) & (disc >= cutoff)).astype(np.uint8)
    log.info(f"Recent (30d): {int(recent.sum()):,} px")
    return _ssaa(recent)


def render(data_dir, out_path):
    world = build_world_array(data_dir)
    explored = _ssaa(world)                       # 0..1 explored coverage
    recent = _load_recent_mask(world.shape)       # 0..1 or None

    if not BASE_MAP_PATH.exists():
        raise FileNotFoundError(f"Base map missing: {BASE_MAP_PATH}")
    base = np.array(Image.open(BASE_MAP_PATH).convert("RGB"), dtype=np.float32)

    # Fog: dark overlay where NOT explored
    fog_alpha = (FOG_OPACITY * (1.0 - explored))[:, :, np.newaxis]
    out = base * (1.0 - fog_alpha) + np.array(COLOR_FOG, dtype=np.float32) * fog_alpha

    # Red recent tint
    if recent is not None:
        a = recent[:, :, np.newaxis]
        out = out * (1.0 - a) + np.array(COLOR_RECENT, dtype=np.float32) * a

    out = np.clip(out, 0, 255).astype(np.uint8)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="RGB").save(out_path)
    log.info(f"Saved → {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    data_dir = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(HERE / "build" / "fog_rgb.png")
    render(data_dir, out)
