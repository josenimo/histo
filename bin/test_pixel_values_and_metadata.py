#!/usr/bin/env python3
"""
Tests preserving actual optical pixel values and OME physical resolution metadata
(PhysicalSizeX, PhysicalSizeY) in `fix_core_ome_tiff.py` and verifies with `paquo` (QuPath 0.7.0).
"""

import sys
import os
import glob
import shutil
import tifffile
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bin.fix_core_ome_tiff import fix_core_tiff

def test_pixel_and_resolution():
    source_img = "results/registration/ashlar/exemplar-002.ome.tif"
    out_dir = "results/coreograph_metadata_test"
    
    print(f"Step 1: Inspecting physical pixel metadata of source image {source_img}...")
    with tifffile.TiffFile(source_img) as tif:
        page = tif.pages[0]
        tags = page.tags
        res_x = tags.get('XResolution', None)
        res_y = tags.get('YResolution', None)
        res_unit = tags.get('ResolutionUnit', None)
        print(f"  Source XResolution: {res_x.value if res_x else None}")
        print(f"  Source YResolution: {res_y.value if res_y else None}")
        print(f"  Source ResolutionUnit: {res_unit.value if res_unit else None}")
        print(f"  Source OME-XML excerpt: {tif.ome_metadata[:300] if tif.ome_metadata else 'None'}")
        
    full_img = tifffile.imread(source_img)
    if full_img.ndim == 2:
        full_img = full_img[None, ...]
    c, h, w = full_img.shape
    
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    
    print(f"\nStep 2: Extracting real optical pixel data for 4 TMA cores...")
    crop_h, crop_w = 3200, 3200
    coords = [
        ("1", 0, 0),
        ("2", 0, max(0, w - crop_w)),
        ("3", max(0, h - crop_h), 0),
        ("4", max(0, h - crop_h), max(0, w - crop_w))
    ]
    
    for core_idx, y, x in coords:
        core_crop = full_img[:, y:min(h, y+crop_h), x:min(w, x+crop_w)]
        out_path = os.path.join(out_dir, f"{core_idx}.tif")
        print(f"  Core {core_idx} pixel range: min={core_crop.min()}, max={core_crop.max()}, mean={core_crop.mean():.2f}")
        # Save raw core crop
        tifffile.imwrite(out_path, core_crop, imagej=True)
        
    print(f"\nStep 3: Running updated fix_core_ome_tiff.py with resolution preservation...")
    fix_core_tiff(out_dir, source_reference_path=source_img)
    
    print(f"\nStep 4: Running paquo QuPath metadata check...")
    cmd = (
        f'PAQUO_QUPATH_DIR="/Applications/QuPath-0.7.0-arm64.app" '
        f'JAVA_HOME="/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home" '
        f'uv run python bin/check_qupath_paquo.py {out_dir}'
    )
    os.system(cmd)

if __name__ == "__main__":
    test_pixel_and_resolution()
