#!/usr/bin/env python3
"""
Inspects image files using `paquo` (QuPath Python interface)
to verify how QuPath interprets image metadata, channel counts (C),
and time point dimensions (T).
"""

import sys
import os
import glob
import tempfile
import shutil
from paquo.projects import QuPathProject

def inspect_qupath_metadata(image_path):
    abs_path = os.path.abspath(image_path)
    print(f"\n========================================================")
    print(f"Inspecting QuPath metadata for: {abs_path}")
    print(f"========================================================")
    
    if not os.path.exists(abs_path):
        print(f"Error: File {abs_path} does not exist.")
        return
        
    tmpdir = tempfile.mkdtemp(prefix="qupath_test_")
    try:
        qp = QuPathProject(tmpdir, mode="w")
        entries = qp.add_image(abs_path)
        if not isinstance(entries, list):
            entries = [entries]
            
        for idx, entry in enumerate(entries):
            print(f"\n--- Entry [{idx+1}/{len(entries)}] ---")
            print(f"  Image Name:     {entry.image_name}")
            print(f"  Width  (X):     {entry.width}")
            print(f"  Height (Y):     {entry.height}")
            print(f"  Z-slices:       {entry.num_z_slices}")
            print(f"  Timepoints (T): {entry.num_timepoints}")
            print(f"  Channels   (C): {entry.num_channels}")
            print(f"  Image Type:     {entry.image_type}")
            
            if entry.num_timepoints > 1:
                print(f"\n  [FAIL/WARNING] QuPath interpreted {entry.num_timepoints} dimensions as TIMEPOINTS (T), not channels (C)!")
            else:
                print(f"\n  [SUCCESS] QuPath correctly interpreted multi-channel optical dimensions as CHANNELS (C={entry.num_channels}, T=1).")
    except Exception as e:
        print(f"Error inspecting QuPath metadata with paquo: {e}")
    finally:
        if os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_qupath_paquo.py <image_path_or_directory>")
        sys.exit(1)
        
    target = sys.argv[1]
    if os.path.isdir(target):
        tifs = sorted(glob.glob(os.path.join(target, "*.tif")) + glob.glob(os.path.join(target, "*.tiff")))
        for f in tifs:
            inspect_qupath_metadata(f)
    else:
        inspect_qupath_metadata(target)
