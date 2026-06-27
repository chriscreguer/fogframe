#!/usr/bin/env python3
"""
snapshot.py — update the daily snapshot + first-discovery log from FoW data.

Reuses render_fog.build_world_array so the snapshot/discovery geometry stays
pixel-aligned with the render. Run once per day before rendering.

  - snapshots/YYYY-MM-DD.npz : binary world array for the bbox (pruned > KEEP_DAYS)
  - snapshots/discovery_log.npz : int32 array, per-pixel first-seen date ordinal

The renderer turns the discovery log into the rolling 30-day red overlay.

Usage:
    python snapshot.py <fow_data_dir>
"""
import sys
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np

import render_fog as rf

HERE = Path(__file__).parent
SNAPSHOT_DIR = HERE / "snapshots"
DISCOVERY_LOG_PATH = SNAPSHOT_DIR / "discovery_log.npz"
KEEP_DAYS = 35

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("snapshot")


def _update_discovery_log(world, today):
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    today_ord = today.toordinal()
    if DISCOVERY_LOG_PATH.exists():
        disc = np.load(DISCOVERY_LOG_PATH)["log"]
        if disc.shape != world.shape:
            log.warning(f"Discovery log shape {disc.shape} ≠ world {world.shape} — resetting")
            disc = np.zeros(world.shape, dtype=np.int32)
    else:
        disc = np.zeros(world.shape, dtype=np.int32)

    new_mask = (world == 1) & (disc == 0)
    n_new = int(new_mask.sum())
    if n_new:
        disc[new_mask] = today_ord
        np.savez_compressed(DISCOVERY_LOG_PATH, log=disc)
        log.info(f"Discovery log: +{n_new:,} new px (total {int((disc > 0).sum()):,})")
    else:
        log.info("Discovery log: no new pixels today")


def _prune(today):
    cutoff = today - timedelta(days=KEEP_DAYS)
    for f in sorted(SNAPSHOT_DIR.glob("*.npz")):
        if f.name == "discovery_log.npz":
            continue
        try:
            if date.fromisoformat(f.stem) < cutoff:
                f.unlink()
                log.info(f"Pruned {f.name}")
        except ValueError:
            continue


def update(data_dir):
    today = date.today()
    world = rf.build_world_array(data_dir)
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    snap_path = SNAPSHOT_DIR / f"{today}.npz"
    np.savez_compressed(snap_path, world=world)
    log.info(f"Saved snapshot {snap_path.name} ({snap_path.stat().st_size/1024:.0f} KB)")
    _update_discovery_log(world, today)
    _prune(today)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    update(sys.argv[1])
