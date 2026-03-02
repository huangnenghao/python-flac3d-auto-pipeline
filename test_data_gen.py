import numpy as np
import rasterio
from rasterio.transform import from_origin
import os
import config

def generate_dummy_tif():
    """
    生成一个用于测试的高斯山丘地形 TIF
    """
    filename = os.path.join(config.INPUT_DIR, "test_terrain.tif")
    
    # 尺寸
    width = 200
    height = 200
    
    # 坐标范围
    x_min = 0.0
    y_max = 2000.0
    pixel_size = 10.0
    
    print(f"Generating dummy TIF: {filename}")
    print(f"Size: {width}x{height}, Pixel Size: {pixel_size}")
    
    # 生成高程数据 (高斯分布模拟山头)
    x = np.linspace(-2, 2, width)
    y = np.linspace(-2, 2, height)
    X, Y = np.meshgrid(x, y)
    
    # Z = 100 * exp(-(x^2 + y^2))
    Z = 100.0 * np.exp(-(X**2 + Y**2))
    
    # 加上一些底噪
    Z += np.random.normal(0, 2, Z.shape)
    
    # 转换为 float32
    Z = Z.astype('float32')
    
    # 定义变换矩阵 (West, North, X_size, Y_size)
    transform = from_origin(x_min, y_max, pixel_size, pixel_size)
    
    # 写入 TIF
    with rasterio.open(
        filename,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=1,
        dtype=Z.dtype,
        crs='+proj=latlong',
        transform=transform,
    ) as dst:
        dst.write(Z, 1)
        
    print("Done. File saved.")

if __name__ == "__main__":
    if not os.path.exists(config.INPUT_DIR):
        os.makedirs(config.INPUT_DIR)
    generate_dummy_tif()
