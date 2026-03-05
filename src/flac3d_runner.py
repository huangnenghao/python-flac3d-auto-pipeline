import os
import subprocess
import time
import sys

class Flac3DRunner:
    def __init__(self):
        self.script_lines = []

    def run_analysis_sequence(self, stl_path, save_path, bounds, config):
        """
        生成 FLAC3D 脚本并调用控制台程序执行全套分析流程
        :param stl_path: 地形 STL 文件绝对路径
        :param save_path: 最终模型保存路径 (可以为 None，如果不依赖此路径保存)
        :param bounds: (xmin, xmax, ymin, ymax, zmin, zmax) 地形包围盒
        :param config: 配置对象
        """
        xmin, xmax, ymin, ymax, z_min_topo, z_max_topo = bounds
        
        # 确保输出目录从 config 获取 (或者从 stl_path 推断，这里假设 config.OUTPUT_DIR 已被 main 更新)
        output_dir = getattr(config, 'OUTPUT_DIR', os.path.dirname(stl_path))

        print(f"[Flac3DRunner] Preparing FLAC3D analysis script...")
        
        # 1. 准备路径和参数
        safe_stl_path = stl_path.replace('\\', '/')
        
        # 如果 save_path 为 None，我们仍然需要一个路径前缀来生成 _balanced.sav
        # 默认使用 output_dir 下的 model.sav 作为基准
        if save_path:
            safe_save_path_base = save_path.replace('\\', '/')
        else:
            safe_save_path_base = os.path.join(output_dir, 'model.sav').replace('\\', '/')
        
        # 网格参数
        res_x = getattr(config, 'MESH_RES_X', 10.0)
        res_y = getattr(config, 'MESH_RES_Y', 10.0)
        # res_z 在 extrude 模式下主要用于计算层数
        res_z = getattr(config, 'MESH_RES_Z', 10.0) 
        
        bot_offset = getattr(config, 'MODEL_BOT_OFFSET', 50.0)
        
        # 计算几何参数
        # 稍微收缩网格范围，确保网格在 STL 覆盖范围内 (参考 debug 脚本 logic)
        margin = res_x * 0.05
        x_min_mesh = xmin + margin
        x_max_mesh = xmax - margin
        y_min_mesh = ymin + margin
        y_max_mesh = ymax - margin
        
        # 模型底面高程
        b_zmin = z_min_topo - bot_offset
        
        # 网格数量
        nx = max(1, int((x_max_mesh - x_min_mesh) / res_x))
        ny = max(1, int((y_max_mesh - y_min_mesh) / res_y))
        
        # 种子层 (Seed Layer) 参数
        seed_height = min(1.0, res_z / 10.0)
        seed_z_top = b_zmin + seed_height
        
        # 挤出层数
        avg_topo_z = (z_min_topo + z_max_topo) / 2.0
        layers = max(1, int((avg_topo_z - seed_z_top) / res_z))

        # 材料参数 (Note: Only used for single-layer fallback, which is deprecated but kept for safety)
        # We construct a default prop string just in case, but usually we use LAYERS
        try:
            mat_props = (
                f"density {getattr(config, 'MAT_DENSITY', 2000.0)} "
                f"young {getattr(config, 'MAT_YOUNG', 1e8)} "
                f"poisson {getattr(config, 'MAT_POISSON', 0.3)} "
                f"cohesion {getattr(config, 'MAT_COHESION', 20e3)} "
                f"friction {getattr(config, 'MAT_FRICTION', 30.0)} "
                f"tension {getattr(config, 'MAT_TENSION', 0.0)}"
            )
        except AttributeError:
             mat_props = "" # Should not happen with getattr default, but safe fallback

        # 2. 构建 FLAC3D 命令序列
        cmds = [
            f"; Auto-generated FLAC3D Analysis Script by GeoMeshAuto",
            f"model new",
            f"model large-strain off",
            
            f"; --- Geometry Import ---",
            f"geometry import '{safe_stl_path}' set 'terrain'",
            
            f"; --- Seed Mesh Generation ---",
            f"zone create brick size {nx} {ny} 1 point 0 ({x_min_mesh}, {y_min_mesh}, {b_zmin}) point 1 ({x_max_mesh}, {y_min_mesh}, {b_zmin}) point 2 ({x_min_mesh}, {y_max_mesh}, {b_zmin}) point 3 ({x_min_mesh}, {y_min_mesh}, {seed_z_top})",
            
            f"; --- Extrude from Topography ---",
            f"zone face group 'seed_top' range position-z {seed_z_top}",
            f"zone generate from-topography geometry-set 'terrain' range group 'seed_top' segments {layers}",
            
            f"; --- Grouping & Properties (Multi-Layer) ---",
            f"zone cmodel assign mohr-coulomb",
        ]

        # 动态生成地层分组和属性赋值命令
        # 我们使用 range geometry-distance 来实现
        # 逻辑：
        # 1. 默认所有单元为最后一层 (bedrock)
        # 2. 然后从倒数第二层开始向上遍历，覆盖之前的设置
        #    例如：先设 bedrock, 然后设 weathered (dist <= 15), 然后设 top_soil (dist <= 5)
        #    这样 dist <= 5 的区域会被 top_soil 覆盖，dist <= 15 但 > 5 的区域保留为 weathered
        
        # 获取地层配置
        layers_config = getattr(config, 'LAYERS', [])
        
        # 如果没有配置 layers，回退到默认单层逻辑 (为了兼容性)
        if not layers_config:
            # 构造一个默认层
            default_props = (
                f"density {config.MAT_DENSITY} "
                f"young {config.MAT_YOUNG} "
                f"poisson {config.MAT_POISSON} "
                f"cohesion {config.MAT_COHESION} "
                f"friction {config.MAT_FRICTION} "
                f"tension {config.MAT_TENSION}"
            )
            cmds.append(f"zone group 'soil_layer' slot 'layers'")
            cmds.append(f"zone property {default_props}")
        else:
            # 1. 首先，将所有单元分配给最后一层 (通常是基岩)
            base_layer = layers_config[-1]
            base_name = base_layer['name']
            
            cmds.append(f"; Initialize all zones to base layer: {base_name}")
            cmds.append(f"zone group '{base_name}' slot 'layers'")
            
            # 2. 从下往上倒序遍历（除了最后一层），利用 geometry-distance 覆盖
            # 注意：config 中是 [top, middle, bottom]，我们需要反过来处理
            # 假设: top (0-2m), middle (2-7m).
            # range geometry-distance gap 7 -> 选中 0-7m 的范围
            # range geometry-distance gap 2 -> 选中 0-2m 的范围
            # 所以，如果我们先应用 gap 7 (middle)，再应用 gap 2 (top)，那么 0-2m 的会被 top 覆盖，2-7m 的保留 middle。
            
            acc_thickness = 0.0
            layer_depths = []
            for layer in layers_config[:-1]:
                if layer['thickness'] is not None:
                    acc_thickness += layer['thickness']
                    layer_depths.append((layer, acc_thickness))
            
            # 倒序遍历 (先处理深的，再处理浅的)
            for layer, depth in reversed(layer_depths):
                layer_name = layer['name']
                cmds.append(f"; Assign layer: {layer_name} (Depth <= {depth}m)")
                # 修正：geometry-distance 不需要 'set' 关键字，直接跟集合名称
                # 语法: range geometry-distance 'terrain' gap {depth}
                cmds.append(f"zone group '{layer_name}' slot 'layers' range geometry-distance 'terrain' gap {depth}")

            # 3. 循环赋值材料参数
            cmds.append(f"; Assign Material Properties")
            for layer in layers_config:
                l_name = layer['name']
                props = layer['mat_props']
                # 注意：此处使用字典 key 获取参数
                prop_str = (
                    f"density {props['density']} "
                    f"young {props['young']} "
                    f"poisson {props['poisson']} "
                    f"cohesion {props['cohesion']} "
                    f"friction {props['friction']} "
                    f"tension {props['tension']}"
                )
                cmds.append(f"zone property {prop_str} range group '{l_name}'")

        # 继续添加剩余命令
        cmds.extend([
            f"; --- Boundary Conditions ---",
            f"zone face apply velocity-z 0 range position-z {b_zmin}",
            f"zone face apply velocity-x 0 range position-x {x_min_mesh}",
            f"zone face apply velocity-x 0 range position-x {x_max_mesh}",
            f"zone face apply velocity-y 0 range position-y {y_min_mesh}",
            f"zone face apply velocity-y 0 range position-y {y_max_mesh}",
            
            f"; --- Initial Equilibrium (Elastic) ---",
            f"model gravity 0 0 {config.GRAVITY_Z}",
            f"model solve elastic ratio {config.SOLVE_ELASTIC_RATIO}",
            
            f"; --- Save Balanced State ---",
            f"model save '{safe_save_path_base.replace('model.sav', 'model_balanced.sav').replace('model_final.sav', 'model_balanced.sav')}'",

            f"; --- Reset State ---",
            f"zone gridpoint initialize displacement (0,0,0)",
            f"zone gridpoint initialize velocity (0,0,0)",
            
            f"; --- Factor of Safety Calculation ---",
            f"model factor-of-safety ratio-local {config.SOLVE_FOS_RATIO}",
            
            f"; --- Final Result ---",
            # f"model save '{safe_save_path}'", # 不需要再保存 model_final.sav
            f"model title 'GeoMeshAuto Final Result'",
            
            f"; quit" # 退出
        ])
        
        # 3. 写入 .dat 脚本文件
        script_path = os.path.join(output_dir, 'run_analysis.dat')
        with open(script_path, 'w') as f:
            f.write('\n'.join(cmds))
        
        print(f"  Script saved to: {script_path}")
        
        # 4. 调用外部 EXE 执行脚本
        exe_path = getattr(config, 'FLAC3D_CONSOLE_PATH', None)
        if not exe_path or not os.path.exists(exe_path):
            print(f"[Flac3DRunner] Error: FLAC3D console executable not found at: {exe_path}")
            return False

        print(f"  Launching FLAC3D Console: {exe_path}")
        print(f"  Executing analysis script (This may take some time)...")
        print("  " + "="*50)
        
        try:
            start_time = time.time()
            
            process = subprocess.Popen(
                [exe_path, script_path],
                cwd=output_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # 实时读取输出
            last_operation = None
            
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    # 简化 FOS 输出逻辑
                    stripped_line = line.strip()
                    
                    # 检查是否是 FOS 计算过程的行 (包含 Bracketing 或 Perturbation)
                    is_fos_line = "Bracketing-" in stripped_line or "Perturbation-" in stripped_line
                    
                    if is_fos_line:
                        # 尝试提取 Operation 名称
                        parts = stripped_line.split()
                        if len(parts) > 0:
                            current_operation = parts[0]
                            # 只有当 Operation 改变时才输出
                            if current_operation != last_operation:
                                sys.stdout.write(f"    [F3D] FOS Progress: {current_operation}...\n")
                                sys.stdout.flush()
                                last_operation = current_operation
                    else:
                        # 过滤掉 FOS 的表头行 (A Operation Step Ratio-loca ...)
                        if "Operation" in stripped_line and "Step" in stripped_line and "Ratio-loca" in stripped_line:
                            continue
                        if "----------" in stripped_line:
                            continue
                            
                        # 非 FOS 步骤，正常输出
                        sys.stdout.write(f"    [F3D] {line}")
                        sys.stdout.flush()

            return_code = process.poll()
            elapsed = time.time() - start_time
            
            print("  " + "="*50)
            
            if return_code == 0:
                print(f"  [Success] FLAC3D analysis completed in {elapsed:.2f}s.")
                return True
            else:
                print(f"  [Failed] FLAC3D exited with code {return_code}.")
                return False

        except Exception as e:
            print(f"  [Error] Failed to launch FLAC3D process: {e}")
            return False
