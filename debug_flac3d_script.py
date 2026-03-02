# ==========================================
# GeoMeshAuto: FLAC3D Debug Script
# 
# 这是一个专用于在 FLAC3D 软件内部运行的调试脚本。
# 使用方法：
# 1. 打开 FLAC3D 软件 (GUI)
# 2. 点击 "Tools" -> "Python" -> "Open Python Script..."
# 3. 选择此文件并运行
# 4. 观察 Console 输出，如有错误可逐行排查
# ==========================================

import itasca as it
# itasca.geometry 似乎不可用，我们将使用原生 Python 读取 STL 文件来计算包围盒
# from itasca import geometry 
import os
import sys
import struct

# 设置工作目录为当前脚本所在目录
# 如果直接在 FLAC3D 中打开，__file__ 可能不可用，此时需手动设置 PROJECT_DIR
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # 如果是在 FLAC3D console 中直接粘贴运行，请手动指定路径
    SCRIPT_DIR = r"d:\2026.03 FLAC3D Code-Native" # 请根据实际情况修改

# 关键文件路径
STL_PATH = os.path.join(SCRIPT_DIR, 'data', 'output', 'terrain_surface.stl')
SAVE_PATH = os.path.join(SCRIPT_DIR, 'data', 'output', 'debug_model.sav')

# 模型参数配置
MESH_RES = 10.0       # 网格尺寸 (米)
TOP_OFFSET = 50.0     # 顶部偏移量 (米)
BOT_OFFSET = 50.0     # 底部偏移量 (米)

def get_stl_bounds(stl_path):
    """
    不依赖第三方库（如 numpy/trimesh），直接解析 ASCII 或 Binary STL 文件获取包围盒
    """
    x_min, x_max = float('inf'), float('-inf')
    y_min, y_max = float('inf'), float('-inf')
    z_min, z_max = float('inf'), float('-inf')
    
    try:
        # 尝试以二进制模式读取
        with open(stl_path, 'rb') as f:
            header = f.read(80)
            count_bytes = f.read(4)
            if len(count_bytes) != 4:
                print("Error reading STL triangle count.")
                return None
            
            num_triangles = struct.unpack('<I', count_bytes)[0]
            # print(f"  (Debug) STL has {num_triangles} triangles")
            
            # 每个三角形 50 字节: Normal(12) + V1(12) + V2(12) + V3(12) + Attr(2)
            # 简单的文件大小检查
            file_size = os.path.getsize(stl_path)
            expected_size = 80 + 4 + num_triangles * 50
            
            if file_size == expected_size:
                # 是二进制 STL
                for _ in range(num_triangles):
                    # 跳过法线 (12 bytes)
                    f.seek(12, 1) 
                    # 读取 3 个顶点 (9 个 float)
                    buffer = f.read(36)
                    if len(buffer) < 36: break
                    
                    floats = struct.unpack('<9f', buffer)
                    # V1 (0,1,2), V2 (3,4,5), V3 (6,7,8)
                    for i in range(0, 9, 3):
                        x, y, z = floats[i], floats[i+1], floats[i+2]
                        if x < x_min: x_min = x
                        if x > x_max: x_max = x
                        if y < y_min: y_min = y
                        if y > y_max: y_max = y
                        if z < z_min: z_min = z
                        if z > z_max: z_max = z
                    
                    # 跳过属性 (2 bytes)
                    f.seek(2, 1)
            else:
                # 可能是 ASCII STL
                # print("  (Debug) Parsing as ASCII STL...")
                with open(stl_path, 'r') as f_txt:
                    for line in f_txt:
                        parts = line.strip().split()
                        if len(parts) == 4 and parts[0] == 'vertex':
                            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                            if x < x_min: x_min = x
                            if x > x_max: x_max = x
                            if y < y_min: y_min = y
                            if y > y_max: y_max = y
                            if z < z_min: z_min = z
                            if z > z_max: z_max = z

        if x_min == float('inf'):
            return None
            
        return (x_min, x_max, y_min, y_max, z_min, z_max)
        
    except Exception as e:
        print(f"Error parsing STL: {e}")
        return None

def run_debug_pipeline():
    print("=== Starting FLAC3D Debug Pipeline ===")
    
    # 1. 初始化模型
    print("[Step 1] Initializing model...")
    it.command("model new")
    it.command("model large-strain off")
    
    # 2. 导入 STL 地形
    print(f"[Step 2] Importing geometry: {STL_PATH}")
    if not os.path.exists(STL_PATH):
        print(f"Error: STL file not found at {STL_PATH}")
        return

    # 注意：FLAC3D 命令中的路径使用单引号
    safe_stl_path = STL_PATH.replace('\\', '/')
    it.command(f"geometry import '{safe_stl_path}' set 'terrain'")
    
    # 3. 计算模型范围 (不再依赖 itasca.geometry)
    print("[Step 3] Calculating model bounds from STL file...")
    bounds = get_stl_bounds(STL_PATH)
    
    if bounds:
        x_min, x_max, y_min, y_max, z_min_topo, z_max_topo = bounds
        print(f"  Terrain Bounds: X[{x_min:.1f}, {x_max:.1f}], Y[{y_min:.1f}, {y_max:.1f}], Z[{z_min_topo:.1f}, {z_max_topo:.1f}]")
    else:
        print("Warning: Failed to calculate bounds from STL. Using default values.")
        x_min, x_max = 0.0, 100.0
        y_min, y_max = 0.0, 100.0
        z_min_topo, z_max_topo = 0.0, 50.0

    # 计算扩展后的模型范围
    b_zmin = z_min_topo - BOT_OFFSET
    b_zmax = z_max_topo + TOP_OFFSET
    
    # 计算网格数量
    nx = max(1, int((x_max - x_min) / MESH_RES))
    ny = max(1, int((y_max - y_min) / MESH_RES))
    nz = max(1, int((b_zmax - b_zmin) / MESH_RES))
    
    print(f"  Mesh Grid: {nx} x {ny} x {nz}")
    
    # 4. 生成初始网格 (Brick)
    print("[Step 4] Creating base mesh...")
    cmd_zone_create = (
        f"zone create brick size {nx} {ny} {nz} "
        f"point 0 ({x_min}, {y_min}, {b_zmin}) "
        f"point 1 ({x_max}, {y_min}, {b_zmin}) "
        f"point 2 ({x_min}, {y_max}, {b_zmin}) "
        f"point 3 ({x_min}, {y_min}, {b_zmax})"
    )
    print(f"  Command: {cmd_zone_create}")
    it.command(cmd_zone_create)
    
    # 5. 地形切割 (Generate from Topography)
    print("[Step 5] Generating mesh from topography...")
    it.command("zone generate from-topography geometry-set 'terrain'")
    
    # 6. 分组与材料赋参
    print("[Step 6] Assigning groups and properties...")
    # 假设所有网格都是土体 (实际项目中可能需要更复杂的逻辑)
    it.command("zone group 'soil_layer'")
    it.command("zone cmodel assign mohr-coulomb")
    
    # 设置示例材料参数 (Density, Young, Poisson, Cohesion, Friction, Tension)
    # 请根据实际岩土参数修改
    props = "density 2000 young 1e8 poisson 0.3 cohesion 20e3 friction 30 tension 0"
    it.command(f"zone property {props}")
    
    # 7. 边界条件
    print("[Step 7] Applying boundary conditions...")
    # 底部固定 (z-velocity = 0)
    it.command("zone face apply velocity-z 0 range position-z " + str(b_zmin))
    # 四周约束法向位移 (简化处理：固定所有侧面的法向速度)
    # 也可以使用 range plane ...
    it.command(f"zone face apply velocity-x 0 range position-x {x_min}")
    it.command(f"zone face apply velocity-x 0 range position-x {x_max}")
    it.command(f"zone face apply velocity-y 0 range position-y {y_min}")
    it.command(f"zone face apply velocity-y 0 range position-y {y_max}")
    
    # 8. 初始应力平衡 (Gravity)
    print("[Step 8] Solving for initial equilibrium (Elastic)...")
    it.command("model gravity 0 0 -9.81")
    # 先把粘聚力设大，防止塑性破坏，计算弹性解
    # 或者直接用 model solve elastic
    # 这里演示标准的 solve elastic 流程
    it.command("model solve elastic ratio 1e-5")
    
    # 9. 归零位移
    print("[Step 9] Resetting displacements...")
    it.command("zone gridpoint initialize displacement (0,0,0)")
    it.command("zone gridpoint initialize velocity (0,0,0)")
    it.command("model save '{0}_elastic.sav'".format(SAVE_PATH.replace('.sav', '')))

    # 10. (可选) 强度折减法计算安全系数
    print("[Step 10] Ready for Factor of Safety (FOS) analysis...")
    # it.command("model factor-of-safety") # 解除注释以运行 FOS 分析
    
    # 保存最终状态
    safe_save_path = SAVE_PATH.replace('\\', '/')
    it.command(f"model save '{safe_save_path}'")
    print(f"=== Pipeline Completed. Model saved to {SAVE_PATH} ===")

if __name__ == "__main__":
    try:
        run_debug_pipeline()
    except Exception as e:
        print(f"\n[Error] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
