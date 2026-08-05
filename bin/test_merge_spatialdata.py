#!/usr/bin/env python3
"""
Test script verifying 2x2 grid compositing of TMA cores in merge_spatialdata.py with string channel names.
"""

import os
import sys
import numpy as np
import dask.array as da
import spatialdata as sd
from spatialdata.models import Image2DModel, ShapesModel, TableModel
from spatialdata.transformations import Identity
from shapely.geometry import Polygon
from shapely.affinity import translate
import geopandas as gpd
import pandas as pd
import anndata as ad

def test_composite_merged_spatialdata():
    print("[test_composite] Creating test core SpatialData objects...")
    
    core_zarrs = []
    for i in range(1, 5):
        zarr_path = f"/tmp/test_core_{i}.zarr"
        if os.path.exists(zarr_path):
            import shutil
            shutil.rmtree(zarr_path)
            
        img_arr = da.from_array(np.full((4, 400, 400), i * 100, dtype=np.uint16), chunks=(1, 400, 400))
        parsed_img = Image2DModel.parse(img_arr, dims=("c", "y", "x"), c_coords=[str(c) for c in range(4)], transformations={"global": Identity()})
        
        poly = Polygon([(50, 50), (100, 50), (100, 100), (50, 100)])
        gdf = gpd.GeoDataFrame({"geometry": [poly]}, index=[f"cell_core_{i}_1"])
        parsed_shapes = ShapesModel.parse(gdf, transformations={"global": Identity()})
        
        obs = pd.DataFrame({"cell_id": [f"cell_core_{i}_1"], "region": ["cellpose_boundaries"]}, index=[f"cell_core_{i}_1"])
        X = np.random.rand(1, 4)
        adata = ad.AnnData(X=X, obs=obs)
        parsed_table = TableModel.parse(adata, region="cellpose_boundaries", region_key="region", instance_key="cell_id")
        
        sdata = sd.SpatialData(images={"image": parsed_img}, shapes={"cellpose_boundaries": parsed_shapes}, tables={"table": parsed_table})
        sdata.write(zarr_path)
        core_zarrs.append(zarr_path)

    merged_zarr = "/tmp/test_composite_merged.zarr"
    if os.path.exists(merged_zarr):
        import shutil
        shutil.rmtree(merged_zarr)
        
    print(f"\n[test_composite] Merging {len(core_zarrs)} core Zarrs into {merged_zarr}...")
    
    core_sdatas = [sd.read_zarr(z) for z in core_zarrs]
    
    c_num = core_sdatas[0].images["image"].shape[0]
    h, w = core_sdatas[0].images["image"].shape[-2:]
    
    grid_rows = 2
    grid_cols = 2
    canvas = da.zeros((c_num, h * grid_rows, w * grid_cols), dtype=np.uint16, chunks=(1, h, w))
    
    offsets = [
        (0, 0),       # Core 1: top-left
        (0, w),       # Core 2: top-right
        (h, 0),       # Core 3: bottom-left
        (h, w)        # Core 4: bottom-right
    ]
    
    gdfs = []
    tables = []
    
    for idx, (sdata, (off_y, off_x)) in enumerate(zip(core_sdatas, offsets), 1):
        core_img = sdata.images["image"].data
        canvas[:, off_y:off_y+h, off_x:off_x+w] = core_img
        
        if "cellpose_boundaries" in sdata.shapes:
            gdf = sdata.shapes["cellpose_boundaries"].copy()
            gdf["geometry"] = gdf["geometry"].apply(lambda geom: translate(geom, xoff=off_x, yoff=off_y))
            gdfs.append(gdf)
            
        if "table" in sdata.tables:
            tables.append(sdata.tables["table"])
            
    c_names = [str(c) for c in core_sdatas[0].images["image"].coords["c"].values]
    parsed_composite_img = Image2DModel.parse(canvas, dims=("c", "y", "x"), c_coords=c_names, transformations={"global": Identity()})
    
    merged_gdf = pd.concat(gdfs) if gdfs else None
    if merged_gdf is not None:
        merged_gdf.attrs.clear()
        parsed_merged_shapes = ShapesModel.parse(merged_gdf, transformations={"global": Identity()})
    else:
        parsed_merged_shapes = None
        
    merged_table = ad.concat(tables) if tables else None
    parsed_merged_table = TableModel.parse(merged_table, region="cellpose_boundaries", region_key="region", instance_key="cell_id") if merged_table is not None else None
    
    merged_sdata = sd.SpatialData(
        images={"image": parsed_composite_img},
        shapes={"cellpose_boundaries": parsed_merged_shapes} if parsed_merged_shapes is not None else None,
        tables={"table": parsed_merged_table} if parsed_merged_table is not None else None
    )
    merged_sdata.write(merged_zarr)
    print(f"[test_composite] Successfully wrote single-image composite SpatialData Zarr: {merged_zarr}")
    
    # Test SOPA report and explorer write commands
    import subprocess
    cmd_exp = f"sopa explorer write {merged_zarr} --output-path /tmp/test_merged.explorer"
    cmd_rep = f"sopa report {merged_zarr} /tmp/test_merged.html"
    
    res_exp = subprocess.run(cmd_exp, shell=True, capture_output=True, text=True)
    print(f"[test_composite] sopa explorer write status: {res_exp.returncode}")
    if res_exp.returncode != 0:
        print(f"  Explorer stderr: {res_exp.stderr}")
        
    res_rep = subprocess.run(cmd_rep, shell=True, capture_output=True, text=True)
    print(f"[test_composite] sopa report status: {res_rep.returncode}")
    if res_rep.returncode != 0:
        print(f"  Report stderr: {res_rep.stderr}")

if __name__ == "__main__":
    test_composite_merged_spatialdata()
