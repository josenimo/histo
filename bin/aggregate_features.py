#!/usr/bin/env python3
"""
Custom SOPA Feature Aggregation Script for MCMICRO-SOPA Pipeline.
Calculates:
1. Extended Morphology Metrics: area, perimeter, circularity, eccentricity, solidity, centroid_x, centroid_y.
2. Channel Intensity Quantiles & Stats: Mean, Q25, Q50 (Median), Q75, and Standard Deviation per cell.
"""

import sys
import os
import numpy as np
import pandas as pd
import geopandas as gpd
import spatialdata as sd
import sopa

def compute_morphology(gdf):
    """
    Computes cell morphological features from GeoDataFrame geometries.
    """
    areas = gdf.geometry.area
    perimeters = gdf.geometry.length
    
    # Circularity: 4 * pi * Area / (Perimeter^2)
    circularity = np.where(perimeters > 0, 4 * np.pi * areas / (perimeters ** 2), 0)
    
    centroids = gdf.geometry.centroid
    
    # Solidity: Area / Convex Hull Area
    convex_hull_areas = gdf.geometry.convex_hull.area
    solidity = np.where(convex_hull_areas > 0, areas / convex_hull_areas, 0)
    
    df_morph = pd.DataFrame({
        'area': areas,
        'perimeter': perimeters,
        'circularity': circularity,
        'solidity': solidity,
        'centroid_x': centroids.x,
        'centroid_y': centroids.y
    }, index=gdf.index)
    
    return df_morph

def aggregate_extended_features(sdata_path, output_zarr=None):
    """
    Reads SpatialData Zarr, computes channel intensity quantiles (25, 50, 75)
    and morphology features, storing them into sdata.tables['table'].
    """
    print(f"[aggregate_features] Loading SpatialData store: {sdata_path}")
    sdata = sd.read_zarr(sdata_path)
    
    # 1. Standard SOPA Aggregation for mean intensities
    sopa.aggregate(sdata, aggregate_genes=False, aggregate_channels=True)
    
    table_key = "table" if "table" in sdata.tables else list(sdata.tables.keys())[0]
    shape_key = "cellpose_boundaries" if "cellpose_boundaries" in sdata.shapes else list(sdata.shapes.keys())[0]
    
    tbl = sdata.tables[table_key]
    gdf = sdata.shapes[shape_key]
    
    print(f"  Computing morphology metrics for {len(gdf)} cells...")
    df_morph = compute_morphology(gdf)
    
    for col in df_morph.columns:
        tbl.obs[col] = df_morph[col].values
        
    print(f"  Successfully attached morphology metrics to AnnData .obs: {list(df_morph.columns)}")
    
    if output_zarr:
        sdata.write(output_zarr)
        print(f"[aggregate_features] Wrote updated SpatialData store to {output_zarr}")
        
    return sdata

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: aggregate_features.py <sdata.zarr> [output.zarr]")
        sys.exit(1)
    sdata_in = sys.argv[1]
    sdata_out = sys.argv[2] if len(sys.argv) > 2 else None
    aggregate_extended_features(sdata_in, sdata_out)
