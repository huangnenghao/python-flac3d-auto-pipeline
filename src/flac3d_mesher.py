import os
import subprocess
import time
import sys

class Flac3DMesher:
    def __init__(self):
        self.script_lines = []

    def run_meshing_sequence(self, stl_path, save_path, bounds, config):
        """
        生成 FLAC3D 脚本并调用控制台程序执行
        :param stl_path: 地形 STL 文件绝对路径
        :param save_path: 最终模型保存路径
        :param bounds: (xmin, xmax, ymin, ymax, zmin, zmax) 地形包围盒
        :param config: 配置对象
        """
        xmin, xmax, ymin, ymax, z_min_topo, z_max_topo = bounds
        
        print(f"[Flac3DMesher] Preparing FLAC3D script...")
        
        # 1. 构建 FLAC3D 命令序列
        safe_stl_path = stl_path.replace('\\', '/')
        safe_save_path = save_path.replace('\\', '/')
        
        # 计算网格参数
        top_offset = getattr(config, 'MODEL_TOP_OFFSET', 50.0)
        bot_offset = getattr(config, 'MODEL_BOT_OFFSET', 50.0)
        
        b_zmin = z_min_topo - bot_offset
        b_zmax = z_max_topo + top_offset
        
        res_x = getattr(config, 'MESH_RES_X', 10.0)
        res_y = getattr(config, 'MESH_RES_Y', 10.0)
        res_z = getattr(config, 'MESH_RES_Z', 10.0)

        nx = max(1, int((xmax - xmin) / res_x))
        ny = max(1, int((ymax - ymin) / res_y))
        nz = max(1, int((b_zmax - b_zmin) / res_z))
        
        # 生成命令列表
        cmds = [
            f"; Auto-generated FLAC3D script by GeoMeshAuto",
            f"model new",
            f"model large-strain off",
            f"geometry import '{safe_stl_path}' set 'terrain'",
            f"zone create brick point 0 ({xmin}, {ymin}, {b_zmin}) point 1 ({xmax}, {ymin}, {b_zmin}) point 2 ({xmin}, {ymax}, {b_zmin}) point 3 ({xmin}, {ymin}, {b_zmax}) size {nx} {ny} {nz}",
            f"zone generate from-topography geometry-set 'terrain'",
            f"zone group 'soil_layer'",
            f"model save '{safe_save_path}'",
            f"model title 'GeoMeshAuto Generated Model'",
            f"; quit"  # 加上 quit 会让 FLAC3D 执行完自动退出，方便批处理
        ]
        
        # 2. 写入 .dat 脚本文件
        script_path = os.path.join(config.OUTPUT_DIR, 'run_meshing.dat')
        with open(script_path, 'w') as f:
            f.write('\n'.join(cmds))
        
        print(f"  Script saved to: {script_path}")
        
        # 3. 调用外部 EXE 执行脚本
        exe_path = getattr(config, 'FLAC3D_CONSOLE_PATH', None)
        if not exe_path or not os.path.exists(exe_path):
            print(f"[Flac3DMesher] Error: FLAC3D console executable not found at: {exe_path}")
            return False

        print(f"  Launching FLAC3D Console: {exe_path}")
        print(f"  Executing script (Real-time Output):\n")
        print("  " + "="*50)
        
        try:
            start_time = time.time()
            
            # 使用 Popen 实现实时输出流
            # bufsize=1 (行缓冲), universal_newlines=True (文本模式)
            process = subprocess.Popen(
                [exe_path, script_path],
                cwd=config.OUTPUT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # 将错误流合并到标准输出
                text=True,
                bufsize=1
            )
            
            # 实时读取并打印输出
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    # 去除行尾换行符，因为 print 会自动加
                    # 使用 sys.stdout.write 可以更精确控制
                    # 在行首加个缩进，区分 FLAC3D 输出和主程序输出
                    sys.stdout.write(f"    [F3D] {line}")
                    sys.stdout.flush()

            # 等待进程完全结束
            return_code = process.poll()
            elapsed = time.time() - start_time
            
            print("  " + "="*50)
            
            if return_code == 0:
                print(f"  [Success] FLAC3D execution completed in {elapsed:.2f}s.")
                return True
            else:
                print(f"  [Failed] FLAC3D exited with code {return_code}.")
                return False

        except Exception as e:
            print(f"  [Error] Failed to launch FLAC3D process: {e}")
            return False
