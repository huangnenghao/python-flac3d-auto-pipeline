import numpy as np
import trimesh

class SurfaceBuilder:
    def __init__(self, x_grid, y_grid, z_grid):
        """
        :param x_grid: 2D array of X coordinates
        :param y_grid: 2D array of Y coordinates
        :param z_grid: 2D array of Z coordinates (elevation)
        """
        self.x = x_grid
        self.y = y_grid
        self.z = z_grid
        self.mesh = None

    def build_mesh(self):
        """
        将规则网格转换为三角面片
        """
        rows, cols = self.z.shape
        
        print(f"[SurfaceBuilder] Generating mesh from {rows}x{cols} grid...")
        
        # 1. 创建顶点数组 (Vertices)
        # 展平所有坐标，堆叠成 (N, 3) 数组
        # order='C' (Row-major): 先遍历列，再遍历行
        vertices = np.column_stack((
            self.x.flatten(),
            self.y.flatten(),
            self.z.flatten()
        ))
        
        # 2. 创建面片索引 (Faces)
        # 这是一个规则网格，每个格子由两个三角形组成
        
        # 生成左上角点的索引矩阵 (排除最后一行和最后一列)
        # ids 是一个 (rows-1, cols-1) 的矩阵，存储了每个网格左上角顶点的全局 index
        r_idx, c_idx = np.meshgrid(np.arange(rows - 1), np.arange(cols - 1), indexing='ij')
        
        # 计算全局索引: index = row * cols + col
        top_left = r_idx * cols + c_idx
        top_right = top_left + 1
        bottom_left = top_left + cols
        bottom_right = bottom_left + 1
        
        # 展平
        tl = top_left.flatten()
        tr = top_right.flatten()
        bl = bottom_left.flatten()
        br = bottom_right.flatten()
        
        # 定义两个三角形的面片 (逆时针方向，确保法线朝上)
        # Triangle 1: Top-Left -> Bottom-Left -> Top-Right
        faces_1 = np.column_stack((tl, bl, tr))
        
        # Triangle 2: Top-Right -> Bottom-Left -> Bottom-Right
        faces_2 = np.column_stack((tr, bl, br))
        
        # 合并所有面片
        faces = np.vstack((faces_1, faces_2))
        
        # 3. 创建 Trimesh 对象
        self.mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        
        # 修复法线（可选，但推荐）
        # self.mesh.fix_normals()
        
        print(f"  Mesh generated: {len(vertices)} vertices, {len(faces)} faces.")
        print(f"  Bounding Box:\n    X: {self.mesh.bounds[0][0]:.2f} ~ {self.mesh.bounds[1][0]:.2f}")
        print(f"    Y: {self.mesh.bounds[0][1]:.2f} ~ {self.mesh.bounds[1][1]:.2f}")
        print(f"    Z: {self.mesh.bounds[0][2]:.2f} ~ {self.mesh.bounds[1][2]:.2f}")

    def export_stl(self, filepath):
        if self.mesh is None:
            raise ValueError("Mesh not built yet. Call build_mesh() first.")
        
        print(f"[SurfaceBuilder] Exporting to {filepath}")
        self.mesh.export(filepath)
        print("  Export successful.")
