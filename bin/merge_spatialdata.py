#!/usr/bin/env python3
"""
Merges multiple individual TMA core SpatialData Zarr stores into a single
unified master SpatialData Zarr dataset (e.g. exemplar-002_merged.zarr)
containing 1 image per core, 1 label/shape per core, and 1 table per core.
Updates AnnData region annotations as categorical dtypes so SpatialData links each table cleanly.
"""

import sys
import os
import pandas as pd
import spatialdata as sd

def merge_spatialdata(output_zarr, input_zarrs):
    print(f"[merge_spatialdata] Merging {len(input_zarrs)} SpatialData Zarr stores into {output_zarr}...")
    
    images_dict = {}
    shapes_dict = {}
    tables_dict = {}
    
    for zarr_path in sorted(input_zarrs):
        core_name = os.path.basename(zarr_path).replace('.zarr', '')
        shape_element_name = f"{core_name}_cellpose_boundaries"
        image_element_name = f"{core_name}_image"
        table_element_name = f"{core_name}_table"
        
        print(f"  Reading core Zarr store: {zarr_path} ({core_name})")
        try:
            sdata = sd.read_zarr(zarr_path)
            
            # 1. Store 1 image per core
            if "image" in sdata.images:
                images_dict[image_element_name] = sdata.images["image"]
            else:
                for k in sdata.images.keys():
                    images_dict[f"{core_name}_{k}"] = sdata.images[k]
                    
            # 2. Store 1 shape (segmentation) per core
            if "cellpose_boundaries" in sdata.shapes:
                shapes_dict[shape_element_name] = sdata.shapes["cellpose_boundaries"]
            elif sdata.shapes:
                for k in sdata.shapes.keys():
                    shapes_dict[f"{core_name}_{k}"] = sdata.shapes[k]
                    
            # 3. Store 1 table per core & update region annotation as Categorical
            if "table" in sdata.tables:
                tbl = sdata.tables["table"].copy()
                if "spatialdata_attrs" in tbl.uns:
                    tbl.uns["spatialdata_attrs"]["region"] = shape_element_name
                if "region" in tbl.obs:
                    tbl.obs["region"] = pd.Categorical([shape_element_name] * len(tbl))
                tables_dict[table_element_name] = tbl
            elif hasattr(sdata, "tables") and sdata.tables:
                for k in sdata.tables.keys():
                    tbl = sdata.tables[k].copy()
                    if "spatialdata_attrs" in tbl.uns:
                        tbl.uns["spatialdata_attrs"]["region"] = f"{core_name}_{k}"
                    if "region" in tbl.obs:
                        tbl.obs["region"] = pd.Categorical([f"{core_name}_{k}"] * len(tbl))
                    tables_dict[f"{core_name}_{k}"] = tbl
                    
        except Exception as e:
            print(f"  Warning reading {zarr_path}: {e}")
            
    if not images_dict:
        raise RuntimeError(f"No valid image elements found to merge into {output_zarr}")
        
    merged_sdata = sd.SpatialData(
        images=images_dict,
        shapes=shapes_dict if shapes_dict else None,
        tables=tables_dict if tables_dict else None
    )
    
    if os.path.exists(output_zarr):
        import shutil
        shutil.rmtree(output_zarr)
        
    merged_sdata.write(output_zarr)
    print(f"[merge_spatialdata] Successfully wrote merged SpatialData Zarr to {output_zarr}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: merge_spatialdata.py <output_zarr> <input_zarr_1> [input_zarr_2 ...]")
        sys.exit(1)
        
    out_zarr = sys.argv[1]
    in_zarrs = sys.argv[2:]
    merge_spatialdata(out_zarr, in_zarrs)
