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
MESH_RES_X = 3     # FLAC3D 初始网格 X 方向尺寸
MESH_RES_Y = 3      # FLAC3D 初始网格 Y 方向尺寸
MESH_RES_Z = 4     # FLAC3D 初始网格 Z 方向尺寸
MODEL_BOT_OFFSET = 10.0 # 初始大六面体底部低于地形最低点的距离 (建议足够深以容纳所有地层)

# 地层结构定义 (从上往下)
# thickness : 层厚度 (米)，最后一层可以使用 None 表示延伸到底部
# mat_props : 该层的确定性材料参数
# 随机场参数 (仅在 RF_ENABLED=True 时生效):
#   c_cov    : 粘聚力变异系数 (COV)
#   phi_cov  : 摩擦角变异系数 (COV)
#   scale_h  : 水平相关长度 (m)
#   scale_v  : 垂直相关长度 (m)
LAYERS = [
    {
        "name": "gravel_soil",  # 第四系全新统残坡积层（碎石土）
        "thickness": 3.0,       # 资料显示 1~5m，取均值 3m (较上一个项目薄)
        "mat_props": {
            "density": 2000.0, "young": 3e7, "poisson": 0.35,
            "cohesion": 20e3, "friction": 30.0, "tension": 0.0,
            # 随机场参数：碎石土由于局部夹块石，变异性较大
            "c_cov": 0.35, "phi_cov": 0.20,
            "scale_h": 10.0, "scale_v": 1.0,
        }
    },
    {
        "name": "sandstone_bedrock", # 远古界合桐组（砂岩/板岩基岩）
        "thickness": None,           # 剩余部分全部为基岩
        "mat_props": {
            "density": 2500.0, "young": 1.5e9, "poisson": 0.28,
            "cohesion": 250e3, "friction": 38.0, "tension": 40e3,
            # 随机场参数：基岩相对均匀，但裂隙发育导致一定变异性
            "c_cov": 0.20, "phi_cov": 0.15,
            "scale_h": 30.0, "scale_v": 3.0,
        }
    }
]

# FLAC3D 求解参数
GRAVITY_Z = -9.81      # m/s^2
SOLVE_ELASTIC_RATIO = 1e-5
SOLVE_FOS_RATIO = 1e-4

# ============================================================
# 随机场 & 可靠度分析参数 (Monte Carlo)
# ============================================================
RF_ENABLED = False     # 是否在 FOS 计算后自动执行可靠度分析
RF_NSIM    = 100       # Monte Carlo 模拟次数
RF_ACF     = 1         # 自相关函数类型:
                       #   1 = 单指数 (Single Exponential)
                       #   2 = 平方指数/高斯 (Squared Exponential)
                       #   3 = 余弦指数 (Cosine Exponential)
                       #   4 = 二阶马尔可夫 (Second-Order Markov)
                       #   5 = 线性/三角形 (Linear/Triangular)
RF_RXY     = -0.5      # c 与 phi 之间的互相关系数 (负值表示负相关)

# ============================================================
# 结构-地层相互作用 (SSI) 配置
# ============================================================
SSI_ENABLED = True          # 是否启用结构体建模
SSI_PATH = 'A'              # 'A' = FLAC3D structure 元素, 'B' = Gmsh 实体 zone
SSI_SCHEMA_PATH = None      # LLM 生成的结构 schema 文件路径 (.json 或 .py)
                            # 若为 None，则在项目 input 目录查找 structure_schema.json
SSI_STRICT = True
MAIN_TIF_PATH = r"d:\2026.03 FLAC3D Code-Native\data\test\input\DEM.tif"
MAIN_PROJECT_NAME = "test0330"
MAIN_NON_INTERACTIVE = False
MAIN_AUTO_START_RELIABILITY = None

# --- Path A: FLAC3D Structure 元素参数 ---
STRUCTURE_ELEMENTS = {
    'pile': {
        'young': 3e10,                       # Pa (C30 混凝土)
        'poisson': 0.2,                      # 泊松比
        'derive_section_from_radius': True,  # 优先根据 schema 中的半径自动推导截面参数
        'coupling_stiffness_normal': 1e8,    # N/m/m (法向耦合刚度)
        'coupling_stiffness_shear': 1e8,     # N/m/m (切向耦合刚度)
        'coupling_cohesion': 0,              # Pa (耦合粘聚力)
        'coupling_friction': 30.0,           # degrees (耦合摩擦角)
        'segments': 20,                      # 每根桩的分段数
    },
    'cable': {
        'young': 2e11,                       # Pa (钢绞线/锚索)
        'cross_section_area': 3.14e-4,       # m^2
        'grout_stiffness': 1e8,              # N/m/m
        'grout_cohesion': 1e5,               # N/m
        'grout_friction': 30.0,              # degrees
        'grout_perimeter': 0.2,              # m
        'pretension': 0.0,                   # N
        'segments': 10,
    },
    'beam': {
        'young': 3e10,                       # Pa
        'poisson': 0.2,
        'cross_section_area': 0.25,          # m^2
        'moi_y': 0.005,                      # m^4
        'moi_z': 0.005,                      # m^4
        'moi_polar': 0.01,                   # m^4
        'segments': 10,
    },
}

# --- Path B: Gmsh 网格参数 ---
GMSH_MESH_SIZE_TERRAIN = 2.0     # m, 地质体网格尺寸
GMSH_MESH_SIZE_STRUCTURE = 0.5   # m, 结构体附近网格尺寸
GMSH_MESH_ALGORITHM = 6          # 1=MeshAdapt, 6=Frontal-Delaunay (推荐)
GMSH_OPTIMIZE_QUALITY = True     # 网格优化

# --- 结构体材料参数 (两种路径通用) ---
STRUCTURE_MAT_PROPS = {
    'concrete': {
        'density': 2500.0, 'young': 3e10, 'poisson': 0.2,
        'cohesion': 5e6, 'friction': 45.0, 'tension': 3e6,
    },
}
