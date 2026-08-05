#!/usr/bin/env python3
"""
Converts single or multiple optical microscopy TIFF files (such as dearrayed TMA cores)
into a unified SpatialData Zarr dataset with standardized integer channel coordinates ("0", "1", ...).
"""

import sys
import os
import glob
import tifffile
import spatialdata as sd
from spatialdata.models import Image2DModel

def convert_to_spatialdata(output_zarr, input_path, technology="ome_tif"):
    print(f"[convert_to_spatialdata] Output: {output_zarr}, Input: {input_path}")
    
    if os.path.isfile(input_path):
        tiff_files = [input_path]
    elif os.path.isdir(input_path):
        tiff_files = sorted(glob.glob(os.path.join(input_path, "*[0-9]*.tif")) + glob.glob(os.path.join(input_path, "*.tiff")))
    else:
        tiff_files = sorted(glob.glob(input_path))
        
    print(f"[convert_to_spatialdata] Detected {len(tiff_files)} TIFF file(s): {tiff_files}")
    
    images_dict = {}
    if len(tiff_files) == 1:
        tf = tiff_files[0]
        arr = tifffile.imread(tf)
        if arr.ndim == 2:
            arr = arr[None, ...]
        c_coords = [str(i) for i in range(arr.shape[0])]
        print(f"[convert_to_spatialdata] Parsing single image element with shape {arr.shape} and channels {c_coords}")
        images_dict["image"] = Image2DModel.parse(arr, dims=("c", "y", "x"), c_coords=c_coords)
    else:
        for tf in tiff_files:
            core_name = "core_" + os.path.basename(tf).split('.')[0]
            arr = tifffile.imread(tf)
            if arr.ndim == 2:
                arr = arr[None, ...]
            c_coords = [str(i) for i in range(arr.shape[0])]
            print(f"[convert_to_spatialdata] Adding image element '{core_name}' with shape {arr.shape} and channels {c_coords}")
            images_dict[core_name] = Image2DModel.parse(arr, dims=("c", "y", "x"), c_coords=c_coords)
            
    sdata = sd.SpatialData(images=images_dict)
    sdata.write(output_zarr)
    print(f"[convert_to_spatialdata] Successfully wrote SpatialData Zarr to {output_zarr}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: convert_to_spatialdata.py <output_zarr> <input_file_or_dir> [technology]")
        sys.exit(1)
        
    out_zarr = sys.argv[1]
    in_target = sys.argv[2]
    tech = sys.argv[3] if len(sys.argv) > 3 else "ome_tif"
    
    convert_to_spatialdata(out_zarr, in_target, tech)
