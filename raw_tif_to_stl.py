import os
import numpy as np
import rasterio
import trimesh
from rasterio.enums import Resampling
import config

def raw_load_tif(filepath, downsample_factor=1):
    print(f"[RawLoader] Opening {filepath}...")
    with rasterio.open(filepath) as src:
        # Calculate new shape
        new_height = src.height // downsample_factor
        new_width = src.width // downsample_factor
        
        print(f"  Original Size: {src.width} x {src.height}")
        print(f"  Target Size:   {new_width} x {new_height}")
        
        # Read data directly
        data = src.read(
            1,
            out_shape=(new_height, new_width),
            resampling=Resampling.bilinear
        )
        
        # Handle NoData -> NaN (Essential for valid mesh, but no other processing)
        nodata_val = src.nodata
        if nodata_val is not None:
            mask = (data == nodata_val)
            data = data.astype('float32')
            data[mask] = np.nan
        
        # NOTE: Skipping Erosion and Extrapolation here!
        
        # Generate Grid
        transform = src.transform * src.transform.scale(
            (src.width / data.shape[1]),
            (src.height / data.shape[0])
        )
        
        rows, cols = np.indices(data.shape)
        xs, ys = rasterio.transform.xy(transform, rows, cols, offset='center')
        
        return np.array(xs), np.array(ys), data

def raw_build_stl(x, y, z, output_path):
    print(f"[RawBuilder] Generating raw mesh...")
    rows, cols = z.shape
    
    # 1. Vertices
    vertices = np.column_stack((x.flatten(), y.flatten(), z.flatten()))
    
    # 2. Faces
    r_idx, c_idx = np.meshgrid(np.arange(rows - 1), np.arange(cols - 1), indexing='ij')
    top_left = r_idx * cols + c_idx
    top_right = top_left + 1
    bottom_left = top_left + cols
    bottom_right = bottom_left + 1
    
    tl = top_left.flatten()
    tr = top_right.flatten()
    bl = bottom_left.flatten()
    br = bottom_right.flatten()
    
    faces_1 = np.column_stack((tl, bl, tr))
    faces_2 = np.column_stack((tr, bl, br))
    raw_faces = np.vstack((faces_1, faces_2))
    
    # 3. Remove invalid faces (containing NaN)
    # Even in "raw" mode, we cannot have triangles with undefined vertices in STL
    v_z = vertices[:, 2]
    faces_z = v_z[raw_faces]
    invalid_mask = np.isnan(faces_z).any(axis=1)
    valid_faces = raw_faces[~invalid_mask]
    
    print(f"  Total Faces: {len(raw_faces)}")
    print(f"  Valid Faces: {len(valid_faces)}")
    
    # 4. Create Mesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=valid_faces, process=False)
    mesh.remove_unreferenced_vertices()
    
    # NOTE: Skipping PCA Alignment and Centering!
    # The mesh will retain original GeoTIFF coordinates (likely large numbers)
    
    print(f"  Exporting raw STL to {output_path}")
    mesh.export(output_path)
    print(f"  Done. Saved to {output_path}")

if __name__ == "__main__":
    print("=== Raw TIF to STL Converter (No Preprocessing) ===")
    
    # 获取项目名称
    project_name = input(f"Enter project name (default: {config.PROJECT_NAME}): ").strip()
    if not project_name:
        project_name = config.PROJECT_NAME
    
    # 获取路径
    dirs = config.get_project_dirs(project_name)
    input_dir = dirs['input']
    output_dir = dirs['output']
    
    # Find input TIF
    if not os.path.exists(input_dir):
        print(f"Input directory not found: {input_dir}")
        exit()
        
    tif_files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.tif', '.tiff'))]
    if not tif_files:
        print(f"No .tif files found in {input_dir}")
        exit()
        
    input_path = os.path.join(input_dir, tif_files[0])
    # Save to a distinct filename for comparison
    output_path = os.path.join(output_dir, "raw_terrain_no_process.stl")
    
    # Ensure output dir exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Run conversion
    x, y, z = raw_load_tif(input_path, downsample_factor=config.DOWNSAMPLE_FACTOR)
    raw_build_stl(x, y, z, output_path)
