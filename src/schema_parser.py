"""
StructureSchemaParser: 解析 LLM 生成的结构 SCHEMA，处理单位转换和坐标对齐。

SCHEMA 格式参考 generated_rhino_model（参考）.py 中的 SCHEMA dict：
  - meta: 元数据（单位、置信度、假设等）
  - primitives: 几何体列表（box, cylinder, polyline_extrude, line_segment）
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
                has_center = 'center' in prim
                has_endpoints = 'base_center' in prim and 'top_center' in prim
                if (not has_center and not has_endpoints) or 'radius' not in prim or 'height' not in prim:
                    errors.append(
                        f"primitives[{i}] (cylinder): missing 'center' or ('base_center','top_center'), "
                        f"'radius', or 'height'"
                    )
                else:
                    if has_center:
                        center = prim['center']
                        if not isinstance(center, (list, tuple)) or len(center) != 3:
                            errors.append(f"primitives[{i}] (cylinder): 'center' must be a 3D point")
                    if has_endpoints:
                        if not isinstance(prim['base_center'], (list, tuple)) or len(prim['base_center']) != 3:
                            errors.append(f"primitives[{i}] (cylinder): 'base_center' must be a 3D point")
                        if not isinstance(prim['top_center'], (list, tuple)) or len(prim['top_center']) != 3:
                            errors.append(f"primitives[{i}] (cylinder): 'top_center' must be a 3D point")
                    if prim['radius'] <= 0:
                        errors.append(f"primitives[{i}] (cylinder): 'radius' must be positive")
                    if prim['height'] <= 0:
                        errors.append(f"primitives[{i}] (cylinder): 'height' must be positive")
            elif ptype == 'polyline_extrude':
                if 'profile' not in prim or 'height' not in prim:
                    errors.append(f"primitives[{i}] (polyline_extrude): missing 'profile' or 'height'")
            elif ptype in ('line_segment', 'member'):
                if 'start' not in prim or 'end' not in prim:
                    errors.append(f"primitives[{i}] ({ptype}): missing 'start' or 'end'")
                else:
                    if not isinstance(prim['start'], (list, tuple)) or len(prim['start']) != 3:
                        errors.append(f"primitives[{i}] ({ptype}): 'start' must be a 3D point")
                    if not isinstance(prim['end'], (list, tuple)) or len(prim['end']) != 3:
                        errors.append(f"primitives[{i}] ({ptype}): 'end' must be a 3D point")
                    if np.allclose(prim['start'], prim['end']):
                        errors.append(f"primitives[{i}] ({ptype}): 'start' and 'end' must be different")
                if 'radius' in prim and prim['radius'] <= 0:
                    errors.append(f"primitives[{i}] ({ptype}): 'radius' must be positive")
                if 'area' in prim and prim['area'] <= 0:
                    errors.append(f"primitives[{i}] ({ptype}): 'area' must be positive")

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
            if 'center' in prim:
                prim['center'] = [v * scale for v in prim['center']]
            if 'base_center' in prim:
                prim['base_center'] = [v * scale for v in prim['base_center']]
            if 'top_center' in prim:
                prim['top_center'] = [v * scale for v in prim['top_center']]
            prim['radius'] = prim['radius'] * scale
            prim['height'] = prim['height'] * scale

        elif ptype == 'polyline_extrude':
            if 'profile' in prim:
                prim['profile'] = [[v * scale for v in pt] for pt in prim['profile']]
            if 'z0' in prim:
                prim['z0'] = prim['z0'] * scale
            prim['height'] = prim['height'] * scale

        elif ptype in ('line_segment', 'member'):
            prim['start'] = [v * scale for v in prim['start']]
            prim['end'] = [v * scale for v in prim['end']]
            if 'radius' in prim:
                prim['radius'] = prim['radius'] * scale
            if 'area' in prim:
                prim['area'] = prim['area'] * scale * scale
            if 'grout_perimeter' in prim:
                prim['grout_perimeter'] = prim['grout_perimeter'] * scale
            if 'moi_y' in prim:
                prim['moi_y'] = prim['moi_y'] * scale ** 4
            if 'moi_z' in prim:
                prim['moi_z'] = prim['moi_z'] * scale ** 4
            if 'moi_polar' in prim:
                prim['moi_polar'] = prim['moi_polar'] * scale ** 4

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
            bottom_raw, top_raw = self._get_cylinder_endpoints(prim)
            bottom = transform_fn(bottom_raw)
            top = transform_fn(top_raw)
            prim['base_center'] = list(bottom)
            prim['top_center'] = list(top)
            prim['center'] = bottom
            prim['height'] = top[2] - bottom[2]
            prim['center_mode'] = 'base'
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

        elif ptype in ('line_segment', 'member'):
            prim['start'] = transform_fn(prim['start'])
            prim['end'] = transform_fn(prim['end'])

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

    def _get_cylinder_endpoints(self, prim):
        height = prim['height']

        if 'base_center' in prim and 'top_center' in prim:
            return list(prim['base_center']), list(prim['top_center'])

        center = prim['center']
        center_mode = prim.get('center_mode', 'base').lower()

        if center_mode in ('mid', 'middle', 'center', 'centroid'):
            half_height = height / 2.0
            return (
                [center[0], center[1], center[2] - half_height],
                [center[0], center[1], center[2] + half_height],
            )

        return list(center), [center[0], center[1], center[2] + height]

    def _infer_path_a_element_type(self, prim):
        candidates = [
            prim.get('element_type'),
            prim.get('structure_type'),
            prim.get('member_type'),
            prim.get('role'),
            prim.get('layer'),
        ]

        for candidate in candidates:
            if not candidate:
                continue

            key = str(candidate).strip().lower()
            if key in ('pile', 'piles'):
                return 'pile'
            if key in ('cable', 'cables', 'anchor', 'anchors', 'tieback', 'tiebacks'):
                return 'cable'
            if key in ('beam', 'beams', 'brace', 'braces', 'strut', 'struts'):
                return 'beam'

        return None

    def classify_for_path_a(self):
        """
        提取可用于 Path A（FLAC3D structure 元素）的结构定义。
        目前支持：
          - cylinder + pile layer/type → pile
          - line_segment/member + cable layer/type → cable
          - line_segment/member + beam layer/type → beam
        返回分类后的结构列表。
        """
        piles = []
        cables = []
        beams = []
        supported_ids = set()
        final_ids = set(self.get_structure_ids())
        primitives = self.get_primitives()

        if final_ids:
            primitives = [prim for prim in primitives if prim.get('id') in final_ids]

        for prim in primitives:
            element_type = self._infer_path_a_element_type(prim)

            if prim.get('type') == 'cylinder' and element_type == 'pile':
                bottom, top = self._get_cylinder_endpoints(prim)
                piles.append({
                    'id': prim['id'],
                    'type': 'pile',
                    'center_x': bottom[0],
                    'center_y': bottom[1],
                    'top_x': top[0],
                    'top_y': top[1],
                    'z_bottom': bottom[2],
                    'z_top': top[2],
                    'radius': prim['radius'],
                })
                supported_ids.add(prim['id'])

            elif prim.get('type') in ('line_segment', 'member') and element_type == 'cable':
                cable = {
                    'id': prim['id'],
                    'type': 'cable',
                    'start': list(prim['start']),
                    'end': list(prim['end']),
                }
                for key in ('area', 'radius', 'pretension', 'grout_perimeter'):
                    if key in prim:
                        cable[key] = prim[key]
                cables.append(cable)
                supported_ids.add(prim['id'])

            elif prim.get('type') in ('line_segment', 'member') and element_type == 'beam':
                beam = {
                    'id': prim['id'],
                    'type': 'beam',
                    'start': list(prim['start']),
                    'end': list(prim['end']),
                }
                for key in ('area', 'radius', 'moi_y', 'moi_z', 'moi_polar', 'direction_y'):
                    if key in prim:
                        beam[key] = prim[key]
                beams.append(beam)
                supported_ids.add(prim['id'])

        unsupported = []
        if final_ids:
            unsupported = sorted(final_ids - supported_ids)

        return {
            'piles': piles,
            'cables': cables,
            'beams': beams,
            'unsupported': unsupported,
        }
