# GeoMeshAuto: FLAC3D 自动化边坡分析流水线

**GeoMeshAuto** 是一个完全自动化的岩土工程数值分析工具，旨在打通从“地理高程数据 (TIF)”到“FLAC3D 三维力学计算”的全流程。该项目通过 Python 脚本驱动，实现了地形预处理、三维建模、网格划分、初始地应力平衡以及强度折减法 (FOS) 安全系数计算的无人值守运行。

## ✨ 主要特性

1.  **智能地形处理** (`src/tif_loader.py`)
    *   自动加载 GeoTIFF 高程数据。
    *   支持降采样 (`Downsampling`) 以优化网格数量。
    *   **边缘清理 (Erosion)**: 自动去除 TIF 边缘的噪点和异常高程。
    *   **智能填充 (Extrapolation)**: 使用最近邻扩散算法填充无效值 (NoData)，确保生成完整的矩形计算域，避免网格空洞。

2.  **鲁棒的几何建模** (`src/surface_builder.py`)
    *   将高程点阵转换为高质量的 STL 三角网格。
    *   **自动 PCA 对齐**: 使用主成分分析 (PCA) 自动计算地形的长轴方向，并将其旋转对齐到 X 轴，同时将模型中心移动到原点 (0,0,0)。这对狭长型边坡的建模尤为重要。
    *   **垂帘剔除**: 自动识别并剔除由于无效值导致的“垂帘”状错误面片。

3.  **FLAC3D 全流程自动化** (`src/flac3d_runner.py`)
    *   自动生成 FLAC3D 命令流脚本 (`.dat`)。
    *   **混合网格生成策略**: 采用 "Seed Layer" (种子层) + "Extrude" (地形挤出) 的方式生成六面体网格，完美贴合复杂地形表面。
    *   **全套力学分析**:
        *   材料参数赋值 (Mohr-Coulomb 模型)。
        *   边界条件施加 (底部固定，四周约束法向位移)。
        *   初始地应力平衡 (Elastic Solve)。
        *   位移清零。
        *   **强度折减法 (FOS)** 自动计算边坡安全系数。
    *   **实时监控**: 调用 FLAC3D 控制台程序执行计算，并实时解析输出日志，过滤冗余信息，仅展示关键进度。

## 🛠️ 环境依赖

*   **Python**: 3.8+
*   **FLAC3D**: 7.0+ (需要安装并知道 `flac3d700_console.exe` 的路径)
*   **Python 库**:
    *   `rasterio`: 处理 TIF 地理数据
    *   `trimesh`: 处理 STL 几何网格
    *   `numpy`: 数值计算
    *   `scipy`: 科学计算支持

安装依赖：
```bash
pip install -r requirements.txt
```

## 🚀 快速开始

### 1. 准备数据
将你的地形高程数据文件（`.tif` 或 `.tiff` 格式）放入 `data/input/` 目录中。
> 如果没有数据，可以运行 `python test_data_gen.py` 生成一个测试用的高斯山包地形。

### 2. 配置参数
打开 `config.py` 文件，根据你的实际情况修改配置：

```python
# FLAC3D 可执行文件路径 (必须修改为你的真实路径)
FLAC3D_CONSOLE_PATH = r"C:\Program Files\Itasca\FLAC3D700\exe64\flac3d700_console.exe"

# 网格尺寸
MESH_RES_X = 10.0
MESH_RES_Y = 10.0

# 土层厚度
MODEL_BOT_OFFSET = 50.0

# 材料参数 (密度, 模量, 粘聚力, 摩擦角等)
MAT_DENSITY = 2000.0
MAT_COHESION = 20e3
MAT_FRICTION = 30.0
```

### 3. 运行流水线
在终端中运行主程序：

```bash
python main.py
```

程序启动后，会弹出文件选择框，请选择您的 GeoTIFF 文件。随后程序会询问项目名称（默认为文件名），确认后将自动创建文件夹并开始计算。

### 4. 查看结果
程序运行完成后，结果将保存在 `data/<Project_Name>/output/` 目录：
*   `terrain_surface.stl`: 生成的地形 STL 模型。
*   `run_analysis.dat`: 自动生成的 FLAC3D 分析脚本。
*   `model_balanced.sav`: 初始平衡后的中间状态模型。
*   FOS-Init.sav、FOS-Stable.sav、FOS-Unstable.sav ：包含最终 FOS 计算结果的 FLAC3D 模型文件。: 包含最终 FOS 计算结果的 FLAC3D 模型文件（由 FLAC3D 自动生成）。

## 📂 项目结构

```
d:\2026.03 FLAC3D Code-Native\
├── config.py                 # 全局配置文件 (路径、网格、材料参数)
├── main.py                   # 主程序入口 (包含 GUI 文件选择)
├── requirements.txt          # Python 依赖列表
├── debug_flac3d_script.py    # 用于在 FLAC3D GUI 中手动调试的脚本
├── raw_tif_to_stl.py         # 原始数据转换脚本 (用于效果对比)
├── test_data_gen.py          # 测试数据生成器
├── data/
│   ├── <Project_Name>/       # 自动生成的项目文件夹
│   │   ├── input/            # 存放 .tif 输入文件 (自动复制)
│   │   └── output/           # 存放生成的 STL、脚本和计算结果
│   └── ...
└── src/
    ├── tif_loader.py         # TIF 数据加载与预处理 (Erosion, Extrapolation)
    ├── surface_builder.py    # STL 生成与几何变换 (PCA Alignment)
    └── flac3d_runner.py      # FLAC3D 脚本生成与控制台执行
```

## ⚠️ 注意事项

1.  **FLAC3D 路径**: 请务必在 `config.py` 中正确设置 `FLAC3D_CONSOLE_PATH`，否则程序无法启动计算引擎。
2.  **坐标系**: 本程序会自动将地形移动到原点 (0,0,0) 并根据长轴方向旋转。如果你需要在 FLAC3D 中与原始坐标系对齐，请修改 `src/surface_builder.py` 禁用 PCA 对齐功能。
3.  **网格尺寸**: 如果地形很大，请适当增大 `MESH_RES_X/Y` 或 `DOWNSAMPLE_FACTOR`，否则生成的网格数量可能过大导致计算缓慢。

## 🔧 调试

如果你在自动化流程中遇到问题，可以使用 `debug_flac3d_script.py`：
1.  打开 FLAC3D 软件 (GUI)。
2.  菜单栏选择 `Tools -> Python -> Open Python Script...`。
3.  选择并运行 `debug_flac3d_script.py`。
这允许你在可视化的环境中逐步排查几何导入或网格生成的问题。
