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
                
                # data = np.nan_to_num(data, nan=valid_min) # 原来的逻辑，会导致"垂帘"
                
                # 打印有效值的数量
                valid_count = np.count_nonzero(~np.isnan(data))
                total_count = data.size
                print(f"  Handled NoData values (kept as NaN). Valid points: {valid_count}/{total_count} ({valid_count/total_count*100:.1f}%)")

                # 【新增】边缘噪点清理 (Erosion)
                # 解决边缘异常高程点（小山峰）问题
                print("  Cleaning edge noise (Erosion)...")
                data = self._erode_mask(data, iterations=1)
                
                # 【新增】矩形化外扩 (Extrapolation)
                # 将有效地形向外延伸，填充整个矩形，避免 FLAC3D 建模时网格超出地形范围
                print("  Extrapolating to full rectangle (Nearest Neighbor)...")
                data = self._fill_nodata_nearest(data)

            self.elevation = data

            # 生成坐标网格
            return self._generate_grid(src, data)

    def _fill_nodata_nearest(self, data):
        """
        使用最近邻扩散算法填充 NaN 区域
        （简单迭代实现，无 scipy 依赖）
        """
        # 如果没有 NaN，直接返回
        if not np.isnan(data).any():
            return data
            
        # 为了避免无限循环，设置最大迭代次数（通常对于地形图，几十次迭代足够扩散到边界）
        # 或者直到没有 NaN
        max_iter = 500 
        filled_data = data.copy()
        
        # 初始 mask: 哪些地方是有效值
        valid_mask = ~np.isnan(filled_data)
        
        # 简单的高斯金字塔思想或形态学膨胀：
        # 每一轮，NaN 像素如果邻域有有效值，就取有效值的平均
        
        # 更快的方法：使用 scipy.ndimage.distance_transform_edt (如果有)
        # 这里手写一个简易版：向外膨胀 (Dilation) 并填充值
        
        import time
        t0 = time.time()
        
        for i in range(max_iter):
            # 找到当前的 NaN 区域
            nan_mask = np.isnan(filled_data)
            if not nan_mask.any():
                break
                
            # 找到与有效区域相邻的 NaN 像素 (即 NaN 区域的边缘)
            # 通过膨胀有效区域 mask 来找到这些点
            # 同样使用位移法
            # neighbors: 上下左右
            # 我们想找到：本身是 NaN，但周围有非 NaN 的点
            
            # 构造一个 update_mask: 哪些点在这一轮需要被更新
            # 初始全 False
            update_mask = np.zeros_like(nan_mask)
            
            # 累加器，用于计算平均值
            neighbor_sum = np.zeros_like(filled_data, dtype=np.float32)
            neighbor_count = np.zeros_like(filled_data, dtype=np.float32)
            
            # 检查四个方向
            # Shift Valid Data into NaN holes
            
            # Up neighbor (data shifted down)
            # valid_up = ~np.isnan(shifted_data)
            # 我们直接操作：
            
            # 定义位移切片
            slices = [
                (slice(1, None), slice(None), slice(None, -1), slice(None)), # Down shift (src: up)
                (slice(None, -1), slice(None), slice(1, None), slice(None)), # Up shift (src: down)
                (slice(None), slice(1, None), slice(None), slice(None, -1)), # Right shift (src: left)
                (slice(None), slice(None, -1), slice(None), slice(1, None))  # Left shift (src: right)
            ]
            
            has_update = False
            
            # 为了性能，我们在 Python 循环中只做简单的“最近邻复制”（扩散）
            # 也就是：如果我是 NaN，但我左边有值，我就变成左边的值。
            # 多次迭代后，值会传播出去。
            
            # 优化：交替方向传播（类似扫描线算法），可以加速覆盖
            # Pass 1: Top-Left to Bottom-Right
            # Pass 2: Bottom-Right to Top-Left
            
            # 简单的 NumPy 实现：
            # 1. Forward pass (Left->Right, Top->Bottom)
            # 由于 numpy 主要是向量化的，难以做串行依赖的扫描。
            # 我们还是用迭代膨胀法。
            
            # 这一轮填补的值
            new_filled = filled_data.copy()
            
            # 找所有 NaN
            mask = np.isnan(filled_data)
            
            # 上邻居
            up_val = np.roll(filled_data, 1, axis=0)
            up_val[0, :] = np.nan # 边界处理
            
            # 下邻居
            down_val = np.roll(filled_data, -1, axis=0)
            down_val[-1, :] = np.nan
            
            # 左邻居
            left_val = np.roll(filled_data, 1, axis=1)
            left_val[:, 0] = np.nan
            
            # 右邻居
            right_val = np.roll(filled_data, -1, axis=1)
            right_val[:, -1] = np.nan
            
            # 堆叠所有邻居
            stack = np.dstack((up_val, down_val, left_val, right_val))
            
            # 计算邻居的平均值 (忽略 NaN)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                mean_neighbors = np.nanmean(stack, axis=2)
            
            # 更新：原本是 NaN 且 邻居有值的地方
            update_locs = mask & (~np.isnan(mean_neighbors))
            
            if not np.any(update_locs):
                # 没有新的点被填充，说明可能还有孤立的 NaN 区域无法到达（不太可能，除非全空）
                # 或者已经填满
                break
                
            filled_data[update_locs] = mean_neighbors[update_locs]
            has_update = True
        
        print(f"  Extrapolation done in {i+1} iterations. (Time: {time.time()-t0:.2f}s)")
        return filled_data

    def _erode_mask(self, data, iterations=1):
        """
        对有效数据区域进行腐蚀操作，移除边缘受污染的像素
        :param data: 2D array (elevation)
        :param iterations: 腐蚀次数（向内收缩几层像素）
        """
        for _ in range(iterations):
            mask = ~np.isnan(data)
            # 使用简单的 3x3 邻域检查
            # 如果周围 8 个点中有任何一个为 NaN，则该点也设为 NaN
            # 我们通过位移 (Shift) 来快速实现
            
            # 向上、下、左、右位移，并进行与操作
            # 这里简单实现：
            eroded_mask = mask.copy()
            # 四个方向的平移
            eroded_mask[1:, :] &= mask[:-1, :]   # Down shift -> Up neighbor
            eroded_mask[:-1, :] &= mask[1:, :]   # Up shift -> Down neighbor
            eroded_mask[:, 1:] &= mask[:, :-1]   # Right shift -> Left neighbor
            eroded_mask[:, :-1] &= mask[:, 1:]   # Left shift -> Right neighbor
            
            # 对角线方向（可选，更严格）
            eroded_mask[1:, 1:] &= mask[:-1, :-1]
            eroded_mask[:-1, :-1] &= mask[1:, 1:]
            eroded_mask[1:, :-1] &= mask[:-1, 1:]
            eroded_mask[:-1, 1:] &= mask[1:, :-1]
            
            # 更新数据：将收缩掉的区域设为 NaN
            data[~eroded_mask] = np.nan
            
        return data
        
    def _generate_grid(self, src, data):
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
            
            # 使用 nanmin/nanmax 避免因为 NaN 导致 Z 范围打印错误
            z_min = np.nanmin(self.elevation)
            z_max = np.nanmax(self.elevation)
            print(f"  Data Loaded. Z Range: [{z_min:.2f}, {z_max:.2f}]")
            
            return self.x_grid, self.y_grid, self.elevation
