import os
import re
import subprocess
import time
import sys
import csv
import numpy as np

class Flac3DRunner:
    def __init__(self):
        self.script_lines = []

    def _build_structure_release_cmds(self, structure_cmds):
        release_cmds = []
        if not structure_cmds:
            return release_cmds

        pattern = re.compile(
            r"^structure cable apply tension value\s+.+?\s+range\s+(.+)$",
            re.IGNORECASE
        )

        for cmd in structure_cmds:
            line = cmd.strip()
            match = pattern.match(line)
            if match:
                release_cmds.append(
                    f"structure cable apply tension active off range {match.group(1)}"
                )

        return release_cmds

    def run_analysis_sequence(self, stl_path, save_path, bounds, config, run_fos=True,
                              structure_cmds=None, mesh_import_path=None):
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
            f"; Auto-generated FLAC3D Analysis Script by SlopeRA3D",
            f"model new",
            f"model large-strain off",
        ]

        # --- 网格生成：Path B (Gmsh 导入) 或默认 (seed + extrude) ---
        if mesh_import_path:
            # Path B: 导入 Gmsh 生成的 .f3grid 网格
            safe_mesh_path = mesh_import_path.replace('\\', '/')
            cmds.extend([
                f"; --- Mesh Import (Path B: Gmsh) ---",
                f"zone import '{safe_mesh_path}'",
                f"",
                f"; --- Geometry Import (for reference) ---",
                f"geometry import '{safe_stl_path}' set 'terrain'",
                f"",
                f"; --- Properties ---",
                f"zone cmodel assign mohr-coulomb",
            ])
            # Path B: 分组已在 .f3grid 中定义，跳过 geometry-distance 分组
            # 直接赋值材料属性
        else:
            # 默认路径: seed brick + extrude from topography
            cmds.extend([
                f"; --- Geometry Import ---",
                f"geometry import '{safe_stl_path}' set 'terrain'",
                f"",
                f"; --- Seed Mesh Generation ---",
                f"zone create brick size {nx} {ny} 1 point 0 ({x_min_mesh}, {y_min_mesh}, {b_zmin}) point 1 ({x_max_mesh}, {y_min_mesh}, {b_zmin}) point 2 ({x_min_mesh}, {y_max_mesh}, {b_zmin}) point 3 ({x_min_mesh}, {y_min_mesh}, {seed_z_top})",
                f"",
                f"; --- Extrude from Topography ---",
                f"zone face group 'seed_top' range position-z {seed_z_top}",
                f"zone generate from-topography geometry-set 'terrain' range group 'seed_top' segments {layers}",
                f"",
                f"; --- Grouping & Properties (Multi-Layer) ---",
                f"zone cmodel assign mohr-coulomb",
            ])

        # 动态生成地层分组和属性赋值命令
        # Path B 时分组已在 .f3grid 中，但仍需赋值材料属性
        # 使用 range geometry-distance 来实现分组（仅默认路径）
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
            # --- 分组逻辑（仅默认路径，Path B 分组已在 .f3grid 中）---
            if not mesh_import_path:
                # 1. 首先，将所有单元分配给最后一层 (通常是基岩)
                base_layer = layers_config[-1]
                base_name = base_layer['name']

                cmds.append(f"; Initialize all zones to base layer: {base_name}")
                cmds.append(f"zone group '{base_name}' slot 'layers'")

                # 2. 从下往上倒序遍历（除了最后一层），利用 geometry-distance 覆盖
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
                    cmds.append(f"zone group '{layer_name}' slot 'layers' range geometry-distance 'terrain' gap {depth}")

            # --- 材料属性赋值（两种路径通用）---
            cmds.append(f"; Assign Material Properties")
            for layer in layers_config:
                l_name = layer['name']
                props = layer['mat_props']
                prop_str = (
                    f"density {props['density']} "
                    f"young {props['young']} "
                    f"poisson {props['poisson']} "
                    f"cohesion {props['cohesion']} "
                    f"friction {props['friction']} "
                    f"tension {props['tension']}"
                )
                cmds.append(f"zone property {prop_str} range group '{l_name}'")

        # 注入 structure 元素命令 (Path A)
        release_structure_cmds = self._build_structure_release_cmds(structure_cmds)
        if structure_cmds:
            cmds.append("")
            cmds.extend(structure_cmds)
            cmds.append("")

        # 注入结构体材料属性 (Path A/B 通用)
        struct_mat = getattr(config, 'STRUCTURE_MAT_PROPS', {})
        if struct_mat:
            cmds.append("; --- Structure Material Properties ---")
            for mat_name, props in struct_mat.items():
                # 只有当存在对应 group 时才赋值（由 Gmsh Path B 创建的 zone group）
                if mesh_import_path:
                    prop_str = (
                        f"density {props['density']} "
                        f"young {props['young']} "
                        f"poisson {props['poisson']} "
                        f"cohesion {props['cohesion']} "
                        f"friction {props['friction']} "
                        f"tension {props['tension']}"
                    )
                    cmds.append(f"zone property {prop_str} range group '{mat_name}'")

        # 继续添加剩余命令
        balanced_sav_path = safe_save_path_base.replace('model.sav', 'model_balanced.sav').replace('model_final.sav', 'model_balanced.sav')
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
        ])

        if release_structure_cmds:
            cmds.extend([
                f"; --- Release Pretension Control Before FOS/Balanced Save ---",
                *release_structure_cmds,
                f"model solve elastic ratio {config.SOLVE_ELASTIC_RATIO}",
            ])

        cmds.extend([
            f"; --- Save Balanced State ---",
            f"model save '{balanced_sav_path}'",
        ])

        if run_fos:
            cmds.extend([
                f"; --- Reset State ---",
                f"zone gridpoint initialize displacement (0,0,0)",
                f"zone gridpoint initialize velocity (0,0,0)",

                f"; --- Factor of Safety Calculation ---",
                f"model factor-of-safety ratio-local {config.SOLVE_FOS_RATIO}",

                f"; --- Final Result ---",
                f"model title 'SlopeRA3D Final Result'",
            ])
        else:
            cmds.append(f"; --- FOS skipped (Reliability Analysis will run Monte Carlo FOS) ---")

        cmds.append(f"program quit")  # 通知 FLAC3D 控制台退出，必须是真实命令而非注释
        
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
                stdin=subprocess.DEVNULL,  # 防止 FLAC3D 脚本结束后等待 stdin
                text=True,
                encoding='utf-8',
                errors='replace',
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
            print(f"  [FLAC3D] Process exited (code={return_code}, elapsed={elapsed:.1f}s)")
            print("  " + "="*50)

            if return_code == 0:
                print(f"  [Success] FLAC3D analysis completed in {elapsed:.2f}s.")
                return True
            else:
                print(f"  [Info] FLAC3D exited with code {return_code} (non-zero is normal for FLAC3D).")
                return False

        except Exception as e:
            print(f"  [Error] Failed to launch FLAC3D process: {e}")
            return False

    # ------------------------------------------------------------------
    # 可靠度分析（Monte Carlo + 随机场）
    # ------------------------------------------------------------------

    def run_reliability_sequence(self, output_dir, config):
        """
        生成随机场 Monte Carlo 分析脚本并执行。

        流程：
          1. 将 Monte Carlo Python 脚本写入 output_dir/rf_monte_carlo.py
          2. 生成调用该脚本的 FLAC3D .dat 文件
          3. 调用 FLAC3D 控制台执行
          4. 读取结果并打印统计摘要

        :param output_dir : 输出目录（含 model_balanced.sav）
        :param config     : 配置对象
        :return bool      : 是否成功
        """
        print(f"\n[Flac3DRunner] Preparing Reliability Analysis (Monte Carlo)...")

        # 路径准备
        src_dir         = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
        balanced_sav    = os.path.join(output_dir, 'model_balanced.sav').replace('\\', '/')
        rf_script_path  = os.path.join(output_dir, 'rf_monte_carlo.py')
        dat_script_path = os.path.join(output_dir, 'run_reliability.dat')
        results_csv     = os.path.join(output_dir, 'fos_results.csv')

        # 配置参数
        nsim        = getattr(config, 'RF_NSIM',  100)
        acf_type    = getattr(config, 'RF_ACF',   1)
        r_xy        = getattr(config, 'RF_RXY',   -0.5)
        fos_ratio   = getattr(config, 'SOLVE_FOS_RATIO', 1e-4)
        layers_cfg  = getattr(config, 'LAYERS',   [])

        if not layers_cfg:
            print("  [Error] LAYERS not configured. Cannot run reliability analysis.")
            return False

        # 1. 生成 Monte Carlo Python 脚本（在 FLAC3D 内部执行）
        self._write_rf_monte_carlo_script(
            rf_script_path, src_dir, balanced_sav, results_csv,
            nsim, acf_type, r_xy, fos_ratio, layers_cfg
        )

        # 2. 生成 .dat 脚本，使用 "program python 'filepath'" 调用外部 Python 文件
        # FLAC3D 7.0 正确语法：program python 'absolute/path/to/script.py'
        safe_rf_script = rf_script_path.replace('\\', '/')
        dat_content = (
            f"; Auto-generated Reliability Analysis Script\n"
            f"program call '{safe_rf_script}'\n"
            f"program quit\n"
        )
        with open(dat_script_path, 'w', encoding='utf-8') as f:
            f.write(dat_content)

        print(f"  MC script : {rf_script_path}")
        print(f"  DAT script: {dat_script_path}")

        # 3. 调用 FLAC3D 控制台执行
        exe_path = getattr(config, 'FLAC3D_CONSOLE_PATH', None)
        if not exe_path or not os.path.exists(exe_path):
            print(f"  [Error] FLAC3D console not found: {exe_path}")
            return False

        success = self._execute_script(exe_path, dat_script_path, output_dir, nsim)

        # 4. 读取结果并打印摘要
        if success and os.path.exists(results_csv):
            self._print_reliability_summary(results_csv)

        return success

    def _write_rf_monte_carlo_script(self, script_path, src_dir, balanced_sav,
                                     results_csv, nsim, acf_type, r_xy,
                                     fos_ratio, layers_cfg):
        """
        生成在 FLAC3D 内部运行的 Monte Carlo Python 脚本。
        脚本通过 itasca API 获取单元坐标和分组，调用 RandomFieldGenerator 生成随机场，
        循环执行 FOS 计算并将结果写入 CSV。
        """
        # 将 layers_cfg 序列化为 Python 字面量字符串（嵌入脚本中）
        import pprint
        layers_repr = pprint.pformat(layers_cfg)

        safe_src   = src_dir.replace('\\', '/')
        safe_bsav  = balanced_sav.replace('\\', '/')
        safe_csv   = results_csv.replace('\\', '/')

        script = f"""\
# Auto-generated Monte Carlo Reliability Analysis Script
# Runs inside FLAC3D console via: python execute '<this_file>'
import itasca as it
import numpy as np
import sys
import csv

it.command("python-reset-state false")

# Add project src to path so RandomFieldGenerator can be imported
sys.path.insert(0, r'{safe_src}')
from random_field import RandomFieldGenerator

# ---- Configuration (injected at generation time) ----
NSIM       = {nsim}
ACF_TYPE   = {acf_type}
R_XY       = {r_xy}
FOS_RATIO  = {fos_ratio}
LAYERS_CONFIG = {layers_repr}
BALANCED_SAV  = r'{safe_bsav}'
OUTPUT_CSV    = r'{safe_csv}'
# -----------------------------------------------------

print("[RF] Loading balanced model...")
it.command(f"model restore '{{BALANCED_SAV}}'")

print("[RF] Reading zone data from FLAC3D...")
pos = np.array(it.zonearray.pos())   # shape (N, 3)
n_zones = pos.shape[0]

# Build zone group array
layer_names = [layer['name'] for layer in LAYERS_CONFIG]
zone_groups = np.full(n_zones, 'unknown', dtype=object)
for name in layer_names:
    in_grp = np.array(it.zonearray.in_group(name, 'layers'), dtype=bool)
    zone_groups[in_grp] = name

print(f"[RF] Total zones: {{n_zones}}")
for name in layer_names:
    count = np.sum(zone_groups == name)
    print(f"  Layer '{{name}}': {{count}} zones")

# Generate random field samples
print("[RF] Generating random field samples...")
rf = RandomFieldGenerator(
    layers_config=LAYERS_CONFIG,
    acf_type=ACF_TYPE,
    r_xy=R_XY,
    nsim=NSIM,
    seed=1
)
cohesion_matrix, friction_matrix = rf.generate(pos, zone_groups)
print(f"[RF] Random field generated. Shape: {{cohesion_matrix.shape}}")

# Monte Carlo FOS loop
print(f"[RF] Starting Monte Carlo simulation (Nsim={{NSIM}})...")
results = []
for i in range(NSIM):
    # Restore balanced state
    it.command(f"model restore '{{BALANCED_SAV}}'")
    it.command("zone gridpoint initialize displacement (0,0,0)")
    it.command("zone gridpoint initialize velocity (0,0,0)")

    # Apply random field properties for this simulation
    c_i   = cohesion_matrix[:, i]
    phi_i = np.clip(friction_matrix[:, i], 1.0, 89.0)
    it.zonearray.set_prop_scalar('cohesion', c_i)
    it.zonearray.set_prop_scalar('friction', phi_i)

    # Run FOS (no filename → no intermediate .sav files)
    it.command(f"model factor-of-safety ratio-local {{FOS_RATIO}}")
    fos = it.fos()

    avg_c   = float(np.mean(c_i)) / 1000.0   # Pa → kPa
    avg_phi = float(np.mean(phi_i))
    results.append([i + 1, round(avg_c, 3), round(avg_phi, 3), round(fos, 6)])

    print(f"  [MC] Sim {{i+1:>4d}}/{{NSIM}}: "
          f"avg_c={{avg_c:.1f}} kPa, avg_phi={{avg_phi:.1f}} deg, FOS={{fos:.4f}}")

# Save results to CSV
with open(OUTPUT_CSV, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['sim', 'avg_c_kPa', 'avg_phi_deg', 'FOS'])
    writer.writerows(results)

print(f"[RF] Results saved to: {{OUTPUT_CSV}}")
"""
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)
        print(f"  MC Python script written: {script_path}")

    def _execute_script(self, exe_path, dat_path, cwd, nsim):
        """调用 FLAC3D 控制台执行指定 .dat 脚本，实时过滤输出。"""
        print(f"  Launching FLAC3D for reliability analysis ({nsim} simulations)...")
        print("  " + "=" * 50)

        try:
            start_time = time.time()
            process = subprocess.Popen(
                [exe_path, dat_path],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,  # 防止 FLAC3D 脚本结束后等待 stdin
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1
            )

            last_fos_op = None
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    stripped = line.strip()
                    is_fos_line = "Bracketing-" in stripped or "Perturbation-" in stripped
                    if is_fos_line:
                        parts = stripped.split()
                        if parts:
                            op = parts[0]
                            if op != last_fos_op:
                                sys.stdout.write(f"    [F3D] FOS: {op}...\n")
                                sys.stdout.flush()
                                last_fos_op = op
                    else:
                        if ("Operation" in stripped and "Step" in stripped) or "----------" in stripped:
                            continue
                        sys.stdout.write(f"    [F3D] {line}")
                        sys.stdout.flush()

            rc = process.poll()
            elapsed = time.time() - start_time
            print("  " + "=" * 50)

            if rc == 0:
                print(f"  [Success] Reliability analysis completed in {elapsed:.1f}s.")
                return True
            else:
                print(f"  [Failed] FLAC3D exited with code {rc}.")
                return False

        except Exception as e:
            print(f"  [Error] Failed to launch FLAC3D: {e}")
            return False

    def _print_reliability_summary(self, csv_path):
        """读取 FOS 结果 CSV，计算并打印统计摘要。"""
        fos_values = []
        try:
            with open(csv_path, newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fos_values.append(float(row['FOS']))
        except Exception as e:
            print(f"  [Warning] Could not read results: {e}")
            return

        if not fos_values:
            return

        arr = np.array(fos_values)
        n          = len(arr)
        mean_fos   = np.mean(arr)
        std_fos    = np.std(arr)
        min_fos    = np.min(arr)
        max_fos    = np.max(arr)
        pf         = np.sum(arr < 1.0) / n * 100.0   # 失效概率 (%)
        beta       = mean_fos / std_fos if std_fos > 0 else float('inf')  # 简化可靠度指标

        print("\n  " + "=" * 45)
        print("  === Reliability Analysis Results ===")
        print(f"  Simulations   : {n}")
        print(f"  Mean FOS      : {mean_fos:.4f}")
        print(f"  Std Dev       : {std_fos:.4f}")
        print(f"  Min / Max FOS : {min_fos:.4f} / {max_fos:.4f}")
        print(f"  P(FOS < 1.0)  : {pf:.2f}%  (Failure Probability)")
        print(f"  Beta Index    : {beta:.3f}  (= Mean/Std, simplified)")
        print(f"  Results CSV   : {csv_path}")
        print("  " + "=" * 45)
