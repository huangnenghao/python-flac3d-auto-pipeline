import os

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 项目名称配置 (默认项目)
PROJECT_NAME = "Default_Project"

# 动态生成路径的函数
def get_project_dirs(project_name=PROJECT_NAME):
    project_root = os.path.join(BASE_DIR, 'data', project_name)
    return {
        'root': project_root,
        'input': os.path.join(project_root, 'input'),
        'output': os.path.join(project_root, 'output'),
        'temp': os.path.join(project_root, 'temp')
    }

# FLAC3D 可执行文件路径
# 请确保此路径正确，如有变动请在此修改
FLAC3D_CONSOLE_PATH = r"C:\Program Files\Itasca\FLAC3D700\exe64\flac3d700_console.exe"

# TIF 处理配置
DOWNSAMPLE_FACTOR = 1  # 降采样因子
Z_SCALE = 1.0          # 高程缩放

# STL 输出文件名
STL_FILENAME = 'terrain_surface.stl'

# FLAC3D 网格配置
MESH_RES_X = 5     # FLAC3D 初始网格 X 方向尺寸
MESH_RES_Y = 5      # FLAC3D 初始网格 Y 方向尺寸
MESH_RES_Z = 5      # FLAC3D 初始网格 Z 方向尺寸
MODEL_BOT_OFFSET = 10.0 # 初始大六面体底部低于地形最低点的距离 (建议足够深以容纳所有地层)

# 地层结构定义 (从上往下)
# thickness: 层厚度 (米)，最后一层可以使用 None 表示延伸到底部
# mat_props: 该层的材料参数
LAYERS = [
    {
        "name": "top_soil", 
        "thickness": 2.0,  
        "mat_props": {
            "density": 1800.0, "young": 5e7, "poisson": 0.35, 
            "cohesion": 10e3, "friction": 25.0, "tension": 0.0
        }
    },
    {
        "name": "weathered_rock", 
        "thickness": 5.0, 
        "mat_props": {
            "density": 2200.0, "young": 2e8, "poisson": 0.25, 
            "cohesion": 50e3, "friction": 35.0, "tension": 1e4
        }
    },
    {
        "name": "bedrock",   
        "thickness": None, # 剩余部分全部为基岩
        "mat_props": {
            "density": 2500.0, "young": 1e9, "poisson": 0.2, 
            "cohesion": 200e3, "friction": 45.0, "tension": 1e5
        }
    }
]

# FLAC3D 求解参数
GRAVITY_Z = -9.81      # m/s^2
SOLVE_ELASTIC_RATIO = 1e-5
SOLVE_FOS_RATIO = 1e-4
