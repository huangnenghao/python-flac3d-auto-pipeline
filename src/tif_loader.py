import numpy as np
import rasterio
from rasterio.enums import Resampling
import os

class TifLoader:
    def __init__(self, filepath):
        """
        初始化 TIF 加载器
        :param filepath: .tif 文件绝对路径
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"TIF file not found: {filepath}")
        self.filepath = filepath
        self.meta = None
        self.elevation = None
        self.x_grid = None
        self.y_grid = None

    def load_data(self, downsample_factor=1):
        """
        加载并解析 TIF 数据
        :param downsample_factor: 降采样因子 (int >= 1)
        :return: x_grid, y_grid, elevation (都是 2D numpy array)
        """
        print(f"[TifLoader] Opening {self.filepath}...")
        with rasterio.open(self.filepath) as src:
            # 读取原始元数据
            self.meta = src.meta.copy()
            
            # 计算新的形状
            new_height = src.height // downsample_factor
            new_width = src.width // downsample_factor
            
            print(f"  Original Size: {src.width} x {src.height}")
            print(f"  Target Size:   {new_width} x {new_height} (Factor: {downsample_factor})")

            if new_height <= 1 or new_width <= 1:
                 raise ValueError("Downsample factor too large, resulting grid is too small.")

            # 读取第一波段（高程），并进行重采样
            # out_shape 定义了输出数组的形状 (rows, cols)
            data = src.read(
                1,
                out_shape=(new_height, new_width),
                resampling=Resampling.bilinear
            )
            
            # 处理 NoData (通常是 -9999 或极小值)
            nodata_val = src.nodata
            if nodata_val is not None:
                # 创建掩膜：无效值的位置
                mask = (data == nodata_val)
                
                # 将无效值替换为 NaN
                data = data.astype('float32')
                data[mask] = np.nan
                
                # 计算有效数据的最小值
                valid_min = np.nanmin(data)
                if np.isnan(valid_min):
                    valid_min = 0.0 # 全是 nan 的极端情况
                
                # 【修改】与其用最小值填充，不如保留 NaN，让后续 Mesher 决定是否剔除这些点
                # 或者：用最近邻插值填补空洞 (scipy.interpolate.griddata)
                # 但对于边缘的大片空白，填充最小值会导致"垂帘"效果 (从高处突然垂直掉落到最小值)
                
                # 简单改进：如果需要保证网格矩形完整，我们还是得填充。
                # 但为了避免垂帘，我们可以尝试用边缘值填充，或者干脆不做处理（让 SurfaceBuilder 处理 nan）
                # 这里暂时改为：不做填充，保留 NaN。SurfaceBuilder 生成网格时，如果顶点是 NaN，则不生成该面片。
                
                # data = np.nan_to_num(data, nan=valid_min) # 原来的逻辑
                
                print(f"  Handled NoData values (set to NaN). Min valid Z: {valid_min:.2f}")

            self.elevation = data

            # 生成坐标网格
            # 获取变换矩阵 (适应新的尺寸)
            # transform 负责将像素坐标 (col, row) 映射到 地理坐标 (x, y)
            transform = src.transform * src.transform.scale(
                (src.width / data.shape[1]),
                (src.height / data.shape[0])
            )
            
            # 生成像素中心的网格坐标
            rows, cols = np.indices(data.shape)
            
            # rasterio.transform.xy 返回 (xs, ys)
            # 注意: xy() 方法对于二维数组输入，返回的是二维数组
            xs, ys = rasterio.transform.xy(transform, rows, cols, offset='center')
            
            self.x_grid = np.array(xs)
            self.y_grid = np.array(ys)
            
            print(f"  Data Loaded. Z Range: [{np.min(self.elevation):.2f}, {np.max(self.elevation):.2f}]")
            
            return self.x_grid, self.y_grid, self.elevation
