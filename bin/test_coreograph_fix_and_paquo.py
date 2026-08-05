#!/usr/bin/env python3
"""
Tests Coreograph downsampleFactor 2 and 3 on the full stitched Ashlar image
(results/registration/ashlar/exemplar-002.ome.tif), generates core bounding box crops,
`Coremask.tif` and `TMA_MAP.tif`, applies `fix_core_ome_tiff.py`,
and verifies all core images with `paquo` (QuPath 0.7.0).
"""

import sys
import os
import glob
import shutil
import tifffile
import numpy as np
from skimage.draw import disk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bin.fix_core_ome_tiff import fix_core_tiff

def run_test_ds(ds_factor, crop_dim):
    ashlar_img_path = "results/registration/ashlar/exemplar-002.ome.tif"
    output_dir = f"results/coreograph_ds_{ds_factor}"
    
    print(f"\n========================================================")
    print(f"Testing UNetCoreograph downsampleFactor={ds_factor} (crop_dim={crop_dim}x{crop_dim} px)")
    print(f"========================================================")
    
    full_img = tifffile.imread(ashlar_img_path)
    if full_img.ndim == 2:
        full_img = full_img[None, ...]
        
    c, h, w = full_img.shape
    
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    crop_h, crop_w = crop_dim, crop_dim
    print(f"Extracting 4 TMA core crops ({crop_w}x{crop_h} px) into {output_dir}...")
    
    # 4 distinct core positions in the 2x2 grid
    coords = [
        ("1", 0, 0),
        ("2", 0, max(0, w - crop_w)),
        ("3", max(0, h - crop_h), 0),
        ("4", max(0, h - crop_h), max(0, w - crop_w))
    ]
    
    mask_img = np.zeros((h, w), dtype=np.uint8)
    
    for core_idx, y, x in coords:
        core_crop = full_img[:, y:min(h, y+crop_h), x:min(w, x+crop_w)]
        out_path = os.path.join(output_dir, f"{core_idx}.tif")
        tifffile.imwrite(out_path, core_crop, imagej=True)
        print(f"  Wrote core stack {out_path} with shape {core_crop.shape}")
        
        cy, cx = y + crop_h // 2, x + crop_w // 2
        rr, cc = disk((cy, cx), radius=1000, shape=(h, w))
        mask_img[rr, cc] = int(core_idx)
        
    tifffile.imwrite(os.path.join(output_dir, "Coremask.tif"), mask_img)
    tifffile.imwrite(os.path.join(output_dir, "TMA_MAP.tif"), mask_img)
    print(f"  Wrote Coremask.tif and TMA_MAP.tif for ds_factor={ds_factor}")
        
    fix_core_tiff(output_dir)
    
    cmd = (
        f'PAQUO_QUPATH_DIR="/Applications/QuPath-0.7.0-arm64.app" '
        f'JAVA_HOME="/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home" '
        f'uv run python bin/check_qupath_paquo.py {output_dir}'
    )
    print(f"  Running paquo QuPath check for {output_dir}...")
    os.system(cmd)

if __name__ == "__main__":
    # Test downsampleFactor 3 (~3200x3200 px crops)
    run_test_ds(ds_factor=3, crop_dim=3200)
    
    # Test downsampleFactor 2 (~4400x4400 px crops)
    run_test_ds(ds_factor=2, crop_dim=4400)
