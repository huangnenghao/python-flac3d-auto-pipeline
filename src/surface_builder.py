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
        # PCA 变换参数（build_mesh 后可用，供结构坐标对齐使用）
        self.pca_angle = 0.0    # 主轴与 X 轴夹角（弧度）
        self.centroid = np.array([0.0, 0.0, 0.0])  # 变换前的质心

    def build_mesh(self):
        """
        将规则网格转换为三角面片，并进行：
        1. 无效三角形剔除 (解决垂帘问题)
        2. 居中化 (移动到原点)
        3. PCA 旋转对齐 (长轴对齐 X 轴)
        """
        rows, cols = self.z.shape
        print(f"[SurfaceBuilder] Generating mesh from {rows}x{cols} grid...")
        
        # 1. 创建顶点数组 (Vertices)
        # 展平所有坐标，堆叠成 (N, 3) 数组
        vertices = np.column_stack((
            self.x.flatten(),
            self.y.flatten(),
            self.z.flatten()
        ))
        
        # 2. 创建面片索引 (Faces)
        # 生成左上角点的索引矩阵 (排除最后一行和最后一列)
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
        
        # 合并所有初步面片
        raw_faces = np.vstack((faces_1, faces_2))
        
        # 3. 剔除无效面片 (解决垂帘问题)
        # 检查每个三角形的三个顶点 Z 值是否有效 (非 NaN)
        # 只要有一个顶点是 NaN，该三角形就是无效的
        v_z = vertices[:, 2] # 所有顶点的 Z 值
        
        # 获取每个 face 的三个顶点的 Z 值
        # faces_z shape: (num_faces, 3)
        faces_z = v_z[raw_faces]
        
        # 检查是否包含 NaN
        # np.isnan(faces_z).any(axis=1) 返回一个布尔数组，True 表示该行包含至少一个 NaN
        invalid_mask = np.isnan(faces_z).any(axis=1)
        
        # 保留有效面片
        valid_faces = raw_faces[~invalid_mask]
        
        print(f"  Removed {np.sum(invalid_mask)} invalid faces (drape effect). Kept {len(valid_faces)} faces.")
        
        # 4. 清理顶点 (移除未被引用的顶点，包括那些 NaN 点)
        # 这一步对于后续 PCA 很重要，否则 NaN 点会影响计算
        # trimesh 会自动处理：根据 faces 构建 mesh，然后 remove_unreferenced_vertices
        
        # 先创建一个临时 mesh，包含所有顶点(含NaN)和有效面片
        temp_mesh = trimesh.Trimesh(vertices=vertices, faces=valid_faces, process=False)
        
        # 移除未引用的顶点 (这一步会自动把 NaN 点清理掉，因为它们不构成有效面片)
        temp_mesh.remove_unreferenced_vertices()
        
        # 此时 temp_mesh.vertices 应该都是有效数值了
        print(f"  Cleaned mesh: {len(temp_mesh.vertices)} vertices.")
        
        # 5. 几何变换 (居中 + PCA 旋转)
        self._apply_pca_alignment(temp_mesh)
        
        self.mesh = temp_mesh
        
        print(f"  Final Mesh Bounds:\n    X: {self.mesh.bounds[0][0]:.2f} ~ {self.mesh.bounds[1][0]:.2f}")
        print(f"    Y: {self.mesh.bounds[0][1]:.2f} ~ {self.mesh.bounds[1][1]:.2f}")
        print(f"    Z: {self.mesh.bounds[0][2]:.2f} ~ {self.mesh.bounds[1][2]:.2f}")

    def _apply_pca_alignment(self, mesh):
        """
        对网格进行 PCA 分析，将其旋转使得最大方差方向对齐 X 轴，并移动到原点
        """
        print("  Applying PCA alignment and centering...")
        
        # 获取所有顶点坐标 (N, 3)
        points = mesh.vertices
        
        # 1. 计算质心并归零 (Centering)
        centroid = np.mean(points, axis=0)
        points_centered = points - centroid
        
        # 2. PCA 分析 (仅在 XY 平面上进行，保持 Z 轴垂直)
        # 我们希望旋转是绕 Z 轴的，不改变重力方向
        xy_points = points_centered[:, :2] # 取 (x, y)
        
        # 计算协方差矩阵
        cov_matrix = np.cov(xy_points.T)
        
        # 计算特征值和特征向量
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)
        
        # 排序特征向量 (按特征值从大到小)
        # eigenvectors[:, i] 对应 eigenvalues[i]
        sort_idx = np.argsort(eigenvalues)[::-1]
        sorted_eigenvectors = eigenvectors[:, sort_idx]
        
        # 主方向 (最大特征值对应的向量)
        major_axis = sorted_eigenvectors[:, 0]
        
        # 计算旋转角度 (将 major_axis 旋转到 X 轴 (1, 0))
        # angle = arctan2(y, x)
        angle = np.arctan2(major_axis[1], major_axis[0])

        # 保存 PCA 参数，供外部坐标对齐使用
        self.pca_angle = angle
        self.centroid = centroid.copy()

        print(f"  Principal Axis found. Rotation angle: {np.degrees(-angle):.2f} degrees")
        
        # 构建旋转矩阵 (绕 Z 轴旋转 -angle)
        # 顺时针旋转，把主方向转回 X 轴
        c, s = np.cos(-angle), np.sin(-angle)
        R = np.array([
            [c, -s, 0],
            [s,  c, 0],
            [0,  0, 1]
        ])
        
        # 3. 应用变换
        # 先平移回原点
        mesh.vertices -= centroid
        
        # 再旋转
        # transform method expects a 4x4 matrix
        T = np.eye(4)
        T[:3, :3] = R
        mesh.apply_transform(T)
        
        # 4. 再次微调 Z 轴位置 (可选)
        # 让最低点位于 z=0，或者 z_min 保持原样？
        # 用户通常希望模型位于原点附近。
        # 这里我们将几何中心置于 (0,0)，但 Z 轴保留相对高程
        # 为了方便 FLAC3D 建模，通常将 Z_min 对齐到 0 或者保留原始高程
        # 这里不做 Z 轴的额外平移，只做 XY 居中和旋转

    def export_stl(self, filepath):
        if self.mesh is None:
            raise ValueError("Mesh not built yet. Call build_mesh() first.")
        
        print(f"[SurfaceBuilder] Exporting to {filepath}")
        self.mesh.export(filepath)
        print("  Export successful.")
