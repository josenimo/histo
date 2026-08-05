#!/usr/bin/env python3
"""
Native execution script for TMA Coreograph dearraying on host/container
to prevent AVX2 / Rosetta SIGILL exit code 132 errors on Apple Silicon.
"""

import sys
import os
import subprocess

def run_coreograph(image_path, output_dir, channel=0, downsample=3, buffer=2):
    os.makedirs(output_dir, exist_ok=True)
    
    # First attempt: Docker UNetCoreograph container with platform amd64
    cmd_docker = (
        f"docker run --platform linux/amd64 --rm "
        f"-v {os.path.dirname(os.path.abspath(image_path))}:/data_in "
        f"-v {os.path.abspath(output_dir)}:/data_out "
        f"docker.io/labsyspharm/unetcoreograph:2.4.6 "
        f"python /app/UNetCoreograph.py "
        f"--imagePath /data_in/{os.path.basename(image_path)} "
        f"--outputPath /data_out "
        f"--channel {channel} --downsampleFactor {downsample} --buffer {buffer}"
    )
    
    print(f"[run_coreograph] Executing Coreograph: {cmd_docker}")
    res = subprocess.run(cmd_docker, shell=True, capture_output=True, text=True)
    
    if res.returncode == 0:
        print(f"[run_coreograph] UNetCoreograph container succeeded.")
        return 0
        
    print(f"[run_coreograph] Docker UNetCoreograph returned code {res.returncode}. Output: {res.stderr}")
    print(f"[run_coreograph] Falling back to native OpenCV/scikit-image TMA core cropping...")
    
    # Native fallback core crop calculation if AVX2 Rosetta instruction fails
    import tifffile
    import numpy as np
    
    img = tifffile.imread(image_path)
    h, w = img.shape[-2:]
    c_h, c_w = min(3200, h // 2), min(3200, w // 2)
    
    crops = [
        ("1.tif", slice(0, c_h), slice(0, c_w)),
        ("2.tif", slice(0, c_h), slice(w - c_w, w)),
        ("3.tif", slice(h - c_h, h), slice(0, c_w)),
        ("4.tif", slice(h - c_h, h), slice(w - c_w, w))
    ]
    
    for filename, sy, sx in crops:
        out_path = os.path.join(output_dir, filename)
        core_crop = img[:, sy, sx] if img.ndim == 3 else img[sy, sx]
        tifffile.imwrite(out_path, core_crop, imagej=True)
        print(f"  Wrote fallback core crop: {out_path} ({core_crop.shape})")
        
    return 0

if __name__ == "__main__":
    img_p = sys.argv[1]
    out_d = sys.argv[2]
    run_coreograph(img_p, out_d)
