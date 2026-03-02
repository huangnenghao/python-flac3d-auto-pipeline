import os
import sys
import numpy as np
import config
from src.tif_loader import TifLoader
from src.surface_builder import SurfaceBuilder
from src.flac3d_mesher import Flac3DMesher

def main():
    print("=== GeoMeshAuto: TIF to FLAC3D Pipeline ===")
    
    # ==========================================
    # STEP 0: 环境与路径检查
    # ==========================================
    # 查找 input 目录下所有的 tif 文件
    tif_files = [f for f in os.listdir(config.INPUT_DIR) if f.lower().endswith(('.tif', '.tiff'))]
    
    if not tif_files:
        print(f"[Error] No .tif files found in {config.INPUT_DIR}")
        print("Please place your GeoTIFF file in the 'data/input' folder.")
        print("Or run 'python test_data_gen.py' to generate a dummy TIF for testing.")
        return

    # 默认取第一个 TIF 文件
    input_tif_name = tif_files[0]
    input_tif_path = os.path.join(config.INPUT_DIR, input_tif_name)
    output_stl_path = os.path.join(config.OUTPUT_DIR, config.STL_FILENAME)
    output_model_path = os.path.join(config.OUTPUT_DIR, 'model_final.sav')
    
    # 确保输出目录存在
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    
    # 定义全局变量以便后续步骤使用
    x, y, z = None, None, None
    bounds = None

    # ==========================================
    # STEP 1: TIF 数据加载与处理 (解耦)
    # ==========================================
    print("\n>>> STEP 1: Loading TIF Data...")
    try:
        loader = TifLoader(input_tif_path)
        x, y, z = loader.load_data(downsample_factor=config.DOWNSAMPLE_FACTOR)
        
        # 应用高程缩放
        if config.Z_SCALE != 1.0:
            print(f"  Applying Z-scale: {config.Z_SCALE}")
            z = z * config.Z_SCALE
            
        print("  [Success] TIF data loaded.")
    except Exception as e:
        print(f"  [Failed] Error loading TIF: {e}")
        return # 第一步失败直接退出，无法继续

    # ==========================================
    # STEP 2: STL 地形生成 (解耦)
    # ==========================================
    print("\n>>> STEP 2: Generating STL Surface...")
    try:
        builder = SurfaceBuilder(x, y, z)
        builder.build_mesh()
        builder.export_stl(output_stl_path)
        
        # 计算包围盒，供下一步使用
        bounds = (
            np.min(x), np.max(x),
            np.min(y), np.max(y),
            np.min(z), np.max(z)
        )
        print(f"  [Success] STL generated at: {output_stl_path}")
        print(f"  Terrain Bounds: X[{bounds[0]:.1f}, {bounds[1]:.1f}], Y[{bounds[2]:.1f}, {bounds[3]:.1f}], Z[{bounds[4]:.1f}, {bounds[5]:.1f}]")
    except Exception as e:
        print(f"  [Failed] Error generating STL: {e}")
        import traceback
        traceback.print_exc()
        return # 第二步失败直接退出

    # ==========================================
    # STEP 3: FLAC3D 网格划分 (外部控制台调用)
    # ==========================================
    print("\n>>> STEP 3: FLAC3D Meshing (Console Mode)...")
    try:
        mesher = Flac3DMesher()
        # 直接调用 run_meshing_sequence，内部会处理脚本生成和 EXE 调用
        success = mesher.run_meshing_sequence(output_stl_path, output_model_path, bounds, config)
        
        if success:
             print("  [Success] FLAC3D process finished successfully.")
             print(f"  Model saved to: {output_model_path}")
        else:
             print("  [Warning] FLAC3D process encountered an issue.")
             
    except Exception as e:
        print(f"  [Error] Unexpected error during FLAC3D invocation: {e}")

    print("\n=== Pipeline Completed ===")

if __name__ == "__main__":
    main()
