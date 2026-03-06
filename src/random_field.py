import numpy as np


class RandomFieldGenerator:
    """
    三维随机场生成器（无 itasca 依赖，纯 numpy 实现）

    基于 Cholesky 分解生成对数正态随机场，支持多地层、多变量（c, phi）互相关模拟。

    参数说明：
        layers_config : list of dict，每层包含 name, mat_props（含 c_mu, c_cov, phi_mu, phi_cov, scale_h, scale_v）
        acf_type      : int，自相关函数类型（1~5）
        r_xy          : float，c 与 phi 之间的互相关系数
        nsim          : int，Monte Carlo 模拟次数
        seed          : int，随机数种子（保证可复现）
    """

    ACF_NAMES = {
        1: "Single Exponential",
        2: "Squared Exponential (Gaussian)",
        3: "Cosine Exponential",
        4: "Second-Order Markov",
        5: "Linear (Triangular)",
    }

    def __init__(self, layers_config, acf_type=1, r_xy=-0.5, nsim=100, seed=1):
        self.layers_config = layers_config
        self.acf_type = acf_type
        self.r_xy = r_xy
        self.nsim = nsim
        self.seed = seed

        # 互相关矩阵（c 与 phi 之间）
        self._L1 = np.linalg.cholesky(np.array([[1.0, r_xy], [r_xy, 1.0]]))

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def generate(self, zone_positions, zone_groups):
        """
        为所有单元生成随机场样本。

        :param zone_positions : np.ndarray, shape (N, 3)，每个单元的 (x, y, z) 坐标
        :param zone_groups    : np.ndarray, shape (N,)，每个单元所属地层名称（字符串数组）
        :return (cohesion, friction) : 两个 np.ndarray，shape (N, Nsim)
        """
        n_zones = len(zone_positions)
        cohesion = np.ones((n_zones, self.nsim))
        friction = np.ones((n_zones, self.nsim))

        for layer in self.layers_config:
            layer_name = layer["name"]
            props = layer["mat_props"]

            # 找出属于该层的单元索引
            mask = (zone_groups == layer_name)
            if not np.any(mask):
                print(f"  [RF] Warning: No zones found for layer '{layer_name}', skipping.")
                continue

            layer_positions = zone_positions[mask]
            n_layer = layer_positions.shape[0]
            print(f"  [RF] Generating random field for layer '{layer_name}': {n_layer} zones...")

            c_mu   = props["cohesion"] / 1000.0  # 转换为 kPa，与 cov 量纲对齐
            c_cov  = props["c_cov"]
            phi_mu = props["friction"]
            phi_cov = props["phi_cov"]
            scale_h = props["scale_h"]
            scale_v = props["scale_v"]

            c_samples, phi_samples = self._generate_layer(
                layer_positions, c_mu, c_cov, phi_mu, phi_cov, scale_h, scale_v
            )

            # c_samples 单位 kPa → 转回 Pa 赋给 FLAC3D
            cohesion[mask, :] = c_samples * 1000.0
            friction[mask, :] = phi_samples

        return cohesion, friction

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _generate_layer(self, positions, c_mu, c_cov, phi_mu, phi_cov, scale_h, scale_v):
        """
        为单个地层生成随机场样本。

        :return (c_samples, phi_samples) : shape (n_zones, Nsim)，c 单位 kPa
        """
        n = positions.shape[0]

        # 1. 计算两个变量各自的空间相关矩阵，并做 Cholesky 分解
        R_c   = self._build_correlation_matrix(positions, scale_h, scale_v)
        R_phi = self._build_correlation_matrix(positions, scale_h, scale_v)

        L_c   = self._safe_cholesky(R_c,   name="cohesion")
        L_phi = self._safe_cholesky(R_phi, name="friction")

        # 2. 对数正态参数
        sigma_c,   mu_ln_c   = self._lognormal_params(c_mu,   c_cov)
        sigma_phi, mu_ln_phi = self._lognormal_params(phi_mu, phi_cov)

        # 3. 生成标准正态样本 U，shape (2*n, Nsim)
        np.random.seed(self.seed)
        U = np.random.standard_normal((2 * n, self.nsim))

        # 4. 引入 c-phi 互相关
        # U[:n, :] 对应 c，U[n:, :] 对应 phi
        # 每列做 L1 变换：[c_col, phi_col] = L1 @ [u_c, u_phi]
        U_corr = np.zeros_like(U)
        for j in range(self.nsim):
            pair = np.vstack([U[:n, j], U[n:, j]])   # (2, n)
            pair_corr = self._L1 @ pair               # (2, n)
            U_corr[:n, j] = pair_corr[0]
            U_corr[n:, j] = pair_corr[1]

        # 5. 引入空间相关（Cholesky 变换）
        H_c   = L_c   @ U_corr[:n, :]   # (n, Nsim)
        H_phi = L_phi @ U_corr[n:, :]   # (n, Nsim)

        # 6. 转换为对数正态
        c_samples   = np.exp(mu_ln_c   + sigma_c   * H_c)
        phi_samples = np.exp(mu_ln_phi + sigma_phi * H_phi)

        # 7. 对 phi 做物理约束（0° < phi < 90°）
        phi_samples = np.clip(phi_samples, 1.0, 89.0)

        return c_samples, phi_samples

    def _build_correlation_matrix(self, positions, scale_h, scale_v):
        """
        构建空间相关矩阵，支持 ACF 类型 1~5。

        :param positions : (n, 3) 坐标数组
        :param scale_h   : 水平相关长度
        :param scale_v   : 垂直相关长度
        :return R        : (n, n) 对称相关矩阵
        """
        n = positions.shape[0]
        R = np.zeros((n, n))

        x, y, z = positions[:, 0], positions[:, 1], positions[:, 2]

        for i in range(n):
            dx = np.abs(x[i] - x)
            dy = np.abs(y[i] - y)
            dz = np.abs(z[i] - z)
            R[i, :] = self._acf(dx, dy, dz, scale_h, scale_v)

        return R

    def _acf(self, dx, dy, dz, lh, lv):
        """计算自相关函数值（向量化，返回长度为 n 的数组）"""
        t = self.acf_type

        if t == 1:
            # 单指数（各向异性）
            return np.exp(-2.0 * (np.sqrt(dx**2 + dy**2) / lh + dz / lv))

        elif t == 2:
            # 平方指数（高斯）
            return np.exp(-np.pi * ((dx**2 + dy**2) / lh**2 + dz**2 / lv**2))

        elif t == 3:
            # 余弦指数
            r_h = np.sqrt(dx**2 + dy**2) / lh
            r_v = dz / lv
            return np.exp(-4.0 * (r_h + r_v)) * (1 + 4 * r_h) * (1 + 4 * r_v)

        elif t == 4:
            # 二阶马尔可夫
            r_h = np.sqrt(dx**2 + dy**2) / lh
            r_v = dz / lv
            return np.exp(-(r_h + r_v)) * np.cos(r_h) * np.cos(r_v)

        elif t == 5:
            # 线性（三角形）
            r_h = np.sqrt(dx**2 + dy**2) / lh
            r_v = dz / lv
            val = np.where((r_h < 1.0) & (r_v < 1.0), (1 - r_h) * (1 - r_v), 0.0)
            return val

        else:
            raise ValueError(f"Unsupported ACF type: {t}. Must be 1~5.")

    def _safe_cholesky(self, R, name=""):
        """
        对相关矩阵做 Cholesky 分解，若矩阵不正定则先修正特征值。
        """
        try:
            return np.linalg.cholesky(R)
        except np.linalg.LinAlgError:
            print(f"  [RF] Warning: Correlation matrix for '{name}' is not positive definite. Applying eigenvalue correction...")
            eigvals, eigvecs = np.linalg.eigh(R)
            eigvals = np.maximum(eigvals, 1e-10)
            R_fixed = eigvecs @ np.diag(eigvals) @ eigvecs.T
            return np.linalg.cholesky(R_fixed)

    @staticmethod
    def _lognormal_params(mu, cov):
        """
        由均值和变异系数计算对数正态分布的 sigma_ln 和 mu_ln。
        """
        sigma_ln = np.sqrt(np.log(1.0 + cov**2))
        mu_ln    = np.log(mu) - sigma_ln**2 / 2.0
        return sigma_ln, mu_ln
