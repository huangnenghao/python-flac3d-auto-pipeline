import os

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, 'data', 'input')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data', 'output')
TEMP_DIR = os.path.join(BASE_DIR, 'data', 'temp')

# FLAC3D 可执行文件路径
# 请确保此路径正确，如有变动请在此修改
FLAC3D_CONSOLE_PATH = r"C:\Program Files\Itasca\FLAC3D700\exe64\flac3d700_console.exe"

# TIF 处理配置
DOWNSAMPLE_FACTOR = 1  # 降采样因子
Z_SCALE = 1.0          # 高程缩放

# STL 输出文件名
STL_FILENAME = 'terrain_surface.stl'

# FLAC3D 网格配置
MESH_RES_X = 10.0      # FLAC3D 初始网格 X 方向尺寸
MESH_RES_Y = 10.0      # FLAC3D 初始网格 Y 方向尺寸
MESH_RES_Z = 10.0      # FLAC3D 初始网格 Z 方向尺寸
MODEL_TOP_OFFSET = 50.0 # 初始大六面体顶部高出地形最高点的距离
MODEL_BOT_OFFSET = 50.0 # 初始大六面体底部低于地形最低点的距离
