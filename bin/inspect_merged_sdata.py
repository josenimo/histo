#!/usr/bin/env python3
"""
Inspects and prints the standard SpatialData object call for the merged Zarr dataset.
"""

import sys
import os
import spatialdata as sd

def main():
    zarr_path = sys.argv[1] if len(sys.argv) > 1 else "results/sopa/exemplar-002_merged.zarr"
    if not os.path.exists(zarr_path):
        print(f"[inspect_merged_sdata] Error: Path '{zarr_path}' does not exist.")
        sys.exit(1)
        
    print(f"[inspect_merged_sdata] Loading merged SpatialData Zarr: {zarr_path}")
    sdata = sd.read_zarr(zarr_path)
    
    print("\n===================================================================")
    print("                S P A T I A L D A T A   O B J E C T                ")
    print("===================================================================")
    print(sdata)
    print("===================================================================\n")
    
    print("Images  :", list(sdata.images.keys()))
    print("Shapes  :", list(sdata.shapes.keys()))
    print("Tables  :", list(sdata.tables.keys()))
    print("Coords  :", list(sdata.coordinate_systems))

if __name__ == "__main__":
    main()
