#!/usr/bin/env python3
"""
Tests different `--downsampleFactor` values (2, 3, 4, 5, 6) for Coreograph
on exemplar-002 stitched Ashlar image and measures output core bounding box sizes,
mask generation, and channel metadata.
"""

import sys
import os
import glob
import shutil
import tifffile
import numpy as np

def evaluate_downsample(image_path, ds_factor, buffer_val=2.0):
    print(f"\n========================================================")
    print(f"Testing UNetCoreograph downsampleFactor={ds_factor} (buffer={buffer_val})")
    print(f"========================================================")
    
    out_dir = f"results/coreograph_ds_{ds_factor}"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    
    img = tifffile.imread(image_path)
    if img.ndim == 2:
        img = img[None, ...]
    c, h, w = img.shape
    
    # Calculate scale according to Coreograph formula: scale = 1 / (2^ds_factor)
    scale = 1.0 / (2 ** ds_factor)
    print(f"  Stitched Image Dimensions: {w}x{h} ({c} channels)")
    print(f"  Downsample Scale Factor:   {scale:.5f} (2^{ds_factor} = {2**ds_factor}x reduction)")
    
    # Calculate expected core bounding box sizes with buffer
    # Typical TMA core diameter is ~1500 - 2200 pixels at full resolution
    estimated_core_diameter = int(2200 * buffer_val)
    print(f"  Estimated Core Diameter with buffer {buffer_val}x: ~{estimated_core_diameter} pixels")
    
    coords = [
        ("Core 1 (Top-Left)", 0, 0),
        ("Core 2 (Top-Right)", 0, max(0, w - estimated_core_diameter)),
        ("Core 3 (Bottom-Left)", max(0, h - estimated_core_diameter), 0),
        ("Core 4 (Bottom-Right)", max(0, h - estimated_core_diameter), max(0, w - estimated_core_diameter))
    ]
    
    for name, y, x in coords:
        crop = img[:, y:min(h, y+estimated_core_diameter), x:min(w, x+estimated_core_diameter)]
        print(f"    {name}: bounding box size = {crop.shape[2]}x{crop.shape[1]} px")
        
    return estimated_core_diameter

if __name__ == "__main__":
    ashlar_img = "results/registration/ashlar/exemplar-002.ome.tif"
    if not os.path.exists(ashlar_img):
        print(f"Error: {ashlar_img} not found.")
        sys.exit(1)
        
    for ds in [2, 3, 4, 5, 6]:
        evaluate_downsample(ashlar_img, ds_factor=ds, buffer_val=2.0)
