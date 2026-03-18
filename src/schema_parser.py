"""
StructureSchemaParser: 解析 LLM 生成的结构 SCHEMA，处理单位转换和坐标对齐。

SCHEMA 格式参考 generated_rhino_model（参考）.py 中的 SCHEMA dict：
  - meta: 元数据（单位、置信度、假设等）
  - primitives: 几何体列表（box, cylinder, polyline_extrude）
  - operations: 布尔运算列表（union, difference, intersection）
  - outputs: 最终输出对象标识
"""

import os
import json
import copy
import math
import numpy as np


class StructureSchemaParser:
    """解析、验证、单位转换和坐标变换 LLM 生成的结构 schema。"""

    # 支持的单位到米的转换因子
    UNIT_TO_METERS = {
        'm': 1.0,
        'cm': 0.01,
        'mm': 0.001,
        'km': 1000.0,
        'in': 0.0254,
        'ft': 0.3048,
    }

    def __init__(self):
        self.schema = None
        self.primitives = []
        self.operations = []
        self.unit_scale = 1.0  # 从 schema 单位到米的缩放因子

    def load(self, path):
        """
        从文件加载 SCHEMA。支持 .json 和 .py 文件。
        .py 文件中必须包含名为 SCHEMA 的顶层变量。
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"Schema file not found: {path}")

        ext = os.path.splitext(path)[1].lower()

        if ext == '.json':
            with open(path, 'r', encoding='utf-8') as f:
                self.schema = json.load(f)
        elif ext == '.py':
            self.schema = self._extract_schema_from_py(path)
        else:
            raise ValueError(f"Unsupported schema file format: {ext}. Use .json or .py")

        return self.schema

    def _extract_schema_from_py(self, path):
        """从 .py 文件中提取 SCHEMA 变量。"""
        namespace = {}
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 查找 SCHEMA = { ... } 块 — 通过 exec 安全执行（仅提取数据）
        # 只执行到 SCHEMA 定义为止，不执行函数
        try:
            exec(compile(content, path, 'exec'), {'__builtins__': {}}, namespace)
        except Exception:
            # 如果完整执行失败（如 import rhinoscriptsyntax），尝试提取 SCHEMA 字面量
            namespace = self._extract_schema_literal(content)

        if 'SCHEMA' not in namespace:
            raise ValueError(f"No 'SCHEMA' variable found in {path}")

        return namespace['SCHEMA']

    def _extract_schema_literal(self, content):
        """尝试从 Python 源码中提取 SCHEMA dict 字面量。"""
        import ast

        # 解析 AST，查找 SCHEMA = {...} 赋值
        try:
            tree = ast.parse(content)
        except SyntaxError:
            raise ValueError("Cannot parse .py file as Python source")

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'SCHEMA':
                        try:
                            value = ast.literal_eval(node.value)
                            return {'SCHEMA': value}
                        except (ValueError, TypeError):
                            raise ValueError("SCHEMA is not a literal dict")

        raise ValueError("No SCHEMA assignment found in source")

    def validate(self):
        """验证 schema 必填字段。"""
        if self.schema is None:
            raise ValueError("No schema loaded. Call load() first.")

        errors = []

        # 检查 primitives
        primitives = self.schema.get('primitives', [])
        if not primitives:
            errors.append("'primitives' is empty or missing")

        for i, prim in enumerate(primitives):
            if 'id' not in prim:
                errors.append(f"primitives[{i}]: missing 'id'")
            if 'type' not in prim:
                errors.append(f"primitives[{i}]: missing 'type'")

            ptype = prim.get('type')
            if ptype == 'box':
                if 'origin' not in prim or 'size' not in prim:
                    errors.append(f"primitives[{i}] (box): missing 'origin' or 'size'")
            elif ptype == 'cylinder':
                if 'center' not in prim or 'radius' not in prim or 'height' not in prim:
                    errors.append(f"primitives[{i}] (cylinder): missing 'center', 'radius', or 'height'")
            elif ptype == 'polyline_extrude':
                if 'profile' not in prim or 'height' not in prim:
                    errors.append(f"primitives[{i}] (polyline_extrude): missing 'profile' or 'height'")

        # 检查 operations 引用完整性
        prim_ids = {p['id'] for p in primitives if 'id' in p}
        known_ids = set(prim_ids)

        for i, op in enumerate(self.schema.get('operations', [])):
            if 'op' not in op:
                errors.append(f"operations[{i}]: missing 'op'")

            # 检查引用
            target = op.get('target')
            if target and target not in known_ids:
                errors.append(f"operations[{i}]: target '{target}' not found")

            for ref in op.get('tools', []) + op.get('inputs', []):
                if ref not in known_ids:
                    errors.append(f"operations[{i}]: reference '{ref}' not found")

            # 将 result 加入已知 ID
            result_id = op.get('result') or op.get('id')
            if result_id:
                known_ids.add(result_id)

        if errors:
            raise ValueError("Schema validation failed:\n  " + "\n  ".join(errors))

        return True

    def normalize_units(self, target_unit='m'):
        """
        将 schema 中所有尺寸从源单位转换为目标单位（默认米）。
        源单位从 meta.unit 读取。
        """
        if self.schema is None:
            raise ValueError("No schema loaded")

        source_unit = self.schema.get('meta', {}).get('unit', 'm').lower()
        target_unit = target_unit.lower()

        if source_unit not in self.UNIT_TO_METERS:
            raise ValueError(f"Unknown source unit: {source_unit}")
        if target_unit not in self.UNIT_TO_METERS:
            raise ValueError(f"Unknown target unit: {target_unit}")

        self.unit_scale = self.UNIT_TO_METERS[source_unit] / self.UNIT_TO_METERS[target_unit]

        if abs(self.unit_scale - 1.0) < 1e-10:
            return  # 无需转换

        print(f"[SchemaParser] Converting units: {source_unit} -> {target_unit} (scale={self.unit_scale})")

        # 深拷贝以避免修改原始数据
        self.schema = copy.deepcopy(self.schema)

        # 转换所有 primitives 的尺寸参数
        for prim in self.schema.get('primitives', []):
            self._scale_primitive(prim, self.unit_scale)

        # 更新 meta 中的单位标识
        if 'meta' in self.schema:
            self.schema['meta']['unit'] = target_unit

    def _scale_primitive(self, prim, scale):
        """按比例缩放单个 primitive 的所有尺寸参数。"""
        ptype = prim.get('type')

        if ptype == 'box':
            prim['origin'] = [v * scale for v in prim['origin']]
            prim['size'] = [v * scale for v in prim['size']]

        elif ptype == 'cylinder':
            prim['center'] = [v * scale for v in prim['center']]
            prim['radius'] = prim['radius'] * scale
            prim['height'] = prim['height'] * scale

        elif ptype == 'polyline_extrude':
            if 'profile' in prim:
                prim['profile'] = [[v * scale for v in pt] for pt in prim['profile']]
            if 'z0' in prim:
                prim['z0'] = prim['z0'] * scale
            prim['height'] = prim['height'] * scale

    def apply_transform(self, pca_angle, centroid):
        """
        将结构 schema 坐标变换到与地形相同的坐标系。

        SurfaceBuilder 对地形做了：
          1. 平移：减去质心 centroid
          2. 旋转：绕 Z 轴旋转 -pca_angle

        结构 schema 的坐标需要经过相同变换才能与地形对齐。

        :param pca_angle: PCA 主轴与 X 轴的夹角（弧度），同 SurfaceBuilder 输出
        :param centroid: 地形质心 [cx, cy, cz]，同 SurfaceBuilder 输出
        """
        if self.schema is None:
            raise ValueError("No schema loaded")

        print(f"[SchemaParser] Applying coordinate transform: "
              f"angle={math.degrees(-pca_angle):.2f}deg, centroid=({centroid[0]:.1f}, {centroid[1]:.1f}, {centroid[2]:.1f})")

        c, s = math.cos(-pca_angle), math.sin(-pca_angle)
        cx, cy, cz = centroid

        def transform_point(p):
            """平移后旋转一个 3D 点。"""
            # 1. 平移
            x = p[0] - cx
            y = p[1] - cy
            z = p[2] - cz
            # 2. 绕 Z 轴旋转
            xr = c * x - s * y
            yr = s * x + c * y
            return [xr, yr, z]

        self.schema = copy.deepcopy(self.schema)

        for prim in self.schema.get('primitives', []):
            self._transform_primitive(prim, transform_point)

    def _transform_primitive(self, prim, transform_fn):
        """对单个 primitive 应用坐标变换。"""
        ptype = prim.get('type')

        if ptype == 'box':
            origin = prim['origin']
            size = prim['size']
            # Box 的 8 个顶点变换后取新的 AABB
            corners = []
            for dx in [0, size[0]]:
                for dy in [0, size[1]]:
                    for dz in [0, size[2]]:
                        corners.append(transform_fn([origin[0] + dx, origin[1] + dy, origin[2] + dz]))
            corners = np.array(corners)
            new_min = corners.min(axis=0).tolist()
            new_max = corners.max(axis=0).tolist()
            prim['origin'] = new_min
            prim['size'] = [new_max[i] - new_min[i] for i in range(3)]

        elif ptype == 'cylinder':
            center = prim['center']
            height = prim['height']
            # 变换底部中心和顶部中心
            bottom = transform_fn(center)
            top = transform_fn([center[0], center[1], center[2] + height])
            prim['center'] = bottom
            prim['height'] = top[2] - bottom[2]
            # radius 不受绕 Z 轴旋转影响

        elif ptype == 'polyline_extrude':
            z0 = prim.get('z0', 0)
            if 'profile' in prim:
                prim['profile'] = [
                    transform_fn([pt[0], pt[1], z0])[:2]
                    for pt in prim['profile']
                ]
            transformed_base = transform_fn([0, 0, z0])
            transformed_top = transform_fn([0, 0, z0 + prim['height']])
            prim['z0'] = transformed_base[2]
            prim['height'] = transformed_top[2] - transformed_base[2]

    def parse(self):
        """执行验证后返回解析后的 primitives 和 operations。"""
        self.validate()
        self.primitives = self.schema.get('primitives', [])
        self.operations = self.schema.get('operations', [])
        return self.primitives, self.operations

    def get_primitives(self):
        """返回归一化后的几何体列表。"""
        return self.schema.get('primitives', []) if self.schema else []

    def get_operations(self):
        """返回布尔操作列表。"""
        return self.schema.get('operations', []) if self.schema else []

    def get_meta(self):
        """返回 schema 元数据。"""
        return self.schema.get('meta', {}) if self.schema else {}

    def get_structure_ids(self):
        """返回最终输出结构体的 ID 列表。"""
        if not self.schema:
            return []
        return self.schema.get('outputs', {}).get('final_objects', [])

    def classify_for_path_a(self):
        """
        提取可用于 Path A（FLAC3D structure 元素）的结构定义。
        目前支持：圆柱体（桩）→ pile 元素。
        返回分类后的结构列表。
        """
        piles = []
        for prim in self.get_primitives():
            if prim.get('type') == 'cylinder' and prim.get('layer', '').lower() in ('piles', 'pile'):
                piles.append({
                    'id': prim['id'],
                    'type': 'pile',
                    'center_x': prim['center'][0],
                    'center_y': prim['center'][1],
                    'z_bottom': prim['center'][2],
                    'z_top': prim['center'][2] + prim['height'],
                    'radius': prim['radius'],
                })
        return {'piles': piles}
