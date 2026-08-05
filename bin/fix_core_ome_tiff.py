#!/usr/bin/env python3
"""
Fixes OME-TIFF metadata on dearrayed TMA core TIFF images using `tifffile` with `ome=True`
and physical pixel resolution attributes (PhysicalSizeX, PhysicalSizeY in µm/px)
so that multi-channel optical microscopy axes are correctly recognized as CHANNELS (C)
and physical pixel scaling is preserved in QuPath and ImageJ.
"""

import sys
import glob
import os
import tifffile

def fix_core_tiff(target_dir, source_reference_path=None):
    pattern = os.path.join(target_dir, "*[0-9]*.tif")
    tif_files = glob.glob(pattern)
    print(f"[fix_core_ome_tiff] Found {len(tif_files)} core TIFFs in {target_dir}")
    
    # Extract resolution metadata from source reference image if provided
    res_x, res_y, unit = None, None, None
    phys_size_x, phys_size_y = 0.65, 0.65 # Default 0.65 µm/px if unknown
    
    if source_reference_path and os.path.exists(source_reference_path):
        try:
            with tifffile.TiffFile(source_reference_path) as src_tif:
                page = src_tif.pages[0]
                tags = page.tags
                if 'XResolution' in tags and 'YResolution' in tags:
                    rx = tags['XResolution'].value
                    ry = tags['YResolution'].value
                    res_x = rx[0] / rx[1] if isinstance(rx, tuple) else float(rx)
                    res_y = ry[0] / ry[1] if isinstance(ry, tuple) else float(ry)
                    if res_x > 0 and res_y > 0:
                        # Convert resolution to PhysicalSize in micrometers
                        phys_size_x = 10000.0 / res_x if res_x > 10 else 1.0 / res_x
                        phys_size_y = 10000.0 / res_y if res_y > 10 else 1.0 / res_y
                if 'ResolutionUnit' in tags:
                    unit = tags['ResolutionUnit'].value
        except Exception as e:
            print(f"[fix_core_ome_tiff] Note reading source resolution: {e}")

    for tif_path in tif_files:
        try:
            arr = tifffile.imread(tif_path)
            if arr.ndim == 2:
                arr = arr[None, ...]
            
            # Format explicit OME-TIFF metadata with PhysicalSizeX and PhysicalSizeY
            metadata = {
                'axes': 'CYX',
                'PhysicalSizeX': phys_size_x,
                'PhysicalSizeXUnit': 'µm',
                'PhysicalSizeY': phys_size_y,
                'PhysicalSizeYUnit': 'µm',
                'Channel': {'Name': [f'Channel_{i}' for i in range(1, arr.shape[0] + 1)]}
            }
            
            kwargs = {'photometric': 'minisblack', 'metadata': metadata, 'ome': True}
            if res_x and res_y:
                kwargs['resolution'] = (res_x, res_y)
                if unit:
                    kwargs['resolutionunit'] = unit
                    
            tifffile.imwrite(tif_path, arr, **kwargs)
            print(f"[fix_core_ome_tiff] Formatted OME-TIFF for {os.path.basename(tif_path)} (PhysicalSize={phys_size_x:.3f}µm/px)")
        except Exception as e:
            print(f"[fix_core_ome_tiff] Error processing {tif_path}: {e}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "tma_cores"
    ref_path = sys.argv[2] if len(sys.argv) > 2 else None
    fix_core_tiff(target, ref_path)
