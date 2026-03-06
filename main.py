import os
import sys
import shutil
import numpy as np
import config  
import tkinter as tk
from tkinter import filedialog
from src.tif_loader import TifLoader
from src.surface_builder import SurfaceBuilder
from src.flac3d_runner import Flac3DRunner

def select_tif_file():
    """弹出文件选择对话框选择 TIF 文件"""
    root = tk.Tk()
    root.withdraw() # 隐藏主窗口
    file_path = filedialog.askopenfilename(
        title="Select GeoTIFF File",
        filetypes=[("GeoTIFF files", "*.tif *.tiff"), ("All files", "*.*")]
    )
    return file_path

def main():
    print("=== SlopeRA3D: TIF to FLAC3D Pipeline ===")
    
    # 1. 询问是否选择新文件
    print("Please select a GeoTIFF file to start analysis...")
    selected_tif_path = select_tif_file()
    
    if not selected_tif_path:
        print("[Info] No file selected. Exiting...")
        return

    # 2. 获取项目名称
    # 如果用户没有输入项目名称，则默认使用文件名（不含扩展名）
    default_project_name = os.path.splitext(os.path.basename(selected_tif_path))[0]
    
    project_name = input(f"Enter project name (default: {default_project_name}): ").strip()
    if not project_name:
        project_name = default_project_name
    
    # 更新配置中的路径
    dirs = config.get_project_dirs(project_name)
    input_dir = dirs['input']
    output_dir = dirs['output']
    
    print(f"Current Project: {project_name}")
    print(f"Input Directory: {input_dir}")
    print(f"Output Directory: {output_dir}")

    # ==========================================
    # STEP 0: 环境与路径检查 & 文件准备
    # ==========================================
    
    # 确保目录存在
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    
    # 将选中的 TIF 文件复制到项目的 input 目录
    tif_filename = os.path.basename(selected_tif_path)
    target_tif_path = os.path.join(input_dir, tif_filename)
    
    # 如果目标文件不存在，或者与源文件不同，则复制
    if os.path.abspath(selected_tif_path) != os.path.abspath(target_tif_path):
        print(f"Copying TIF file to project input directory...")
        try:
            shutil.copy2(selected_tif_path, target_tif_path)
            print(f"  [Success] Copied to: {target_tif_path}")
        except Exception as e:
            print(f"  [Error] Failed to copy file: {e}")
            return
    else:
        print(f"  [Info] File already exists in input directory.")

    # 设置 input_tif_path 为项目目录下的文件
    input_tif_path = target_tif_path
    output_stl_path = os.path.join(output_dir, config.STL_FILENAME)
    
    # 传递 output_dir 给 config (或者直接修改 config 对象，但这里我们尽量不修改全局 config)
    # 为了让 flac3d_runner 知道新的 output_dir，我们需要一种方式传递
    # 最简单的是临时修改 config.OUTPUT_DIR
    config.OUTPUT_DIR = output_dir # Hack: 更新全局配置以便后续模块使用

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
        # 【重要修正】必须使用变换后的 Mesh bounds，而不是原始数据的 x,y,z
        # 原始数据未经过 PCA 旋转和居中，坐标与最终导出的 STL 不一致
        if builder.mesh is None:
             raise ValueError("Mesh generation failed, builder.mesh is None")
             
        mesh_bounds = builder.mesh.bounds
        # mesh.bounds 返回 [[xmin, ymin, zmin], [xmax, ymax, zmax]]
        bounds = (
            mesh_bounds[0][0], mesh_bounds[1][0], # xmin, xmax
            mesh_bounds[0][1], mesh_bounds[1][1], # ymin, ymax
            mesh_bounds[0][2], mesh_bounds[1][2]  # zmin, zmax
        )
        print(f"  [Success] STL generated at: {output_stl_path}")
        print(f"  Terrain Bounds: X[{bounds[0]:.1f}, {bounds[1]:.1f}], Y[{bounds[2]:.1f}, {bounds[3]:.1f}], Z[{bounds[4]:.1f}, {bounds[5]:.1f}]")
    except Exception as e:
        print(f"  [Failed] Error generating STL: {e}")
        import traceback
        traceback.print_exc()
        return # 第二步失败直接退出

    # ==========================================
    # STEP 3: FLAC3D 分析计算 (外部控制台调用)
    # ==========================================
    print("\n>>> STEP 3: FLAC3D Analysis (Console Mode)...")
    runner = Flac3DRunner()
    step3_success = False
    try:
        # RF_ENABLED=True 时跳过 STEP 3 的 FOS，由 STEP 4 的 Monte Carlo 代替
        run_fos = not getattr(config, 'RF_ENABLED', False)
        success = runner.run_analysis_sequence(output_stl_path, None, bounds, config, run_fos=run_fos)
        # 以 model_balanced.sav 是否生成作为成功的最终判断，
        # 避免 FLAC3D 控制台退出码非零但实际已完成计算的误判
        balanced_sav = os.path.join(output_dir, 'model_balanced.sav')
        balanced_exists = os.path.exists(balanced_sav)
        print(f"  [Check] model_balanced.sav exists: {balanced_exists}")
        if success or balanced_exists:
            print("  [Success] STEP 3 complete. Balanced model ready.")
            step3_success = True
        else:
            print("  [Warning] FLAC3D process encountered an issue.")
    except Exception as e:
        print(f"  [Error] Unexpected error during FLAC3D invocation: {e}")

    # ==========================================
    # STEP 4: 随机场可靠度分析 (Monte Carlo)
    # ==========================================
    print(f"\n[Pipeline] step3_success={step3_success}, RF_ENABLED={getattr(config, 'RF_ENABLED', False)}")
    if step3_success and getattr(config, 'RF_ENABLED', False):
        print("\n" + "="*55)
        print(">>> STEP 4: Reliability Analysis (Random Field Monte Carlo)")
        print("="*55)
        print(f"  ACF Type : {config.RF_ACF}  |  Nsim : {config.RF_NSIM}  |  r_xy : {config.RF_RXY}")
        print()
        confirm = input("  >>> Start reliability analysis? [Y/n]: ").strip().lower()
        if confirm in ('', 'y', 'yes'):
            try:
                runner.run_reliability_sequence(output_dir, config)
            except Exception as e:
                print(f"  [Error] Unexpected error during reliability analysis: {e}")
        else:
            print("  [Info] Reliability analysis skipped.")
    elif step3_success and not getattr(config, 'RF_ENABLED', False):
        print("\n[Info] RF_ENABLED=False in config.py, skipping reliability analysis.")

    print("\n=== Pipeline Completed ===")

if __name__ == "__main__":
    main()
