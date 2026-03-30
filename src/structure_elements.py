"""
StructureElementGenerator: 生成 FLAC3D structure 元素命令（Path A）。

将 schema_parser 解析出的结构定义转换为 FLAC3D 7.0 的 structure 命令：
  - structure pile create
  - structure cable create
  - structure beam create
  + 对应的属性设置和耦合弹簧参数
"""

import math


class StructureElementGenerator:
    """从解析后的结构 schema 生成 FLAC3D structure 元素命令。"""

    def __init__(self, config):
        """
        :param config: 配置对象，包含 STRUCTURE_ELEMENTS 参数
        """
        self.config = config
        self.elem_config = getattr(config, 'STRUCTURE_ELEMENTS', {})
        self._next_id = 1  # structure 元素 ID 计数器

    def _alloc_id(self):
        """分配唯一的 structure element ID。"""
        sid = self._next_id
        self._next_id += 1
        return sid

    @staticmethod
    def _fmt_num(value):
        return f"{float(value):.12g}"

    @staticmethod
    def _segment_length(start, end):
        return math.sqrt(sum((float(end[i]) - float(start[i])) ** 2 for i in range(3)))

    def generate_all(self, parsed_schema):
        """
        从解析后的 schema 生成所有 structure 元素命令。

        :param parsed_schema: schema_parser.classify_for_path_a() 的返回值
        :return: FLAC3D 命令字符串列表
        """
        cmds = []
        cmds.append("; --- Structure Elements (Path A: Auto-generated) ---")

        piles = parsed_schema.get('piles', [])
        cables = parsed_schema.get('cables', [])
        beams = parsed_schema.get('beams', [])

        if piles:
            cmds.append(f"; Piles: {len(piles)}")
            for pile in piles:
                cmds.extend(self.generate_pile(pile))
                cmds.append("")

        if cables:
            cmds.append(f"; Cables: {len(cables)}")
            for cable in cables:
                cmds.extend(self.generate_cable(cable))
                cmds.append("")

        if beams:
            cmds.append(f"; Beams: {len(beams)}")
            for beam in beams:
                cmds.extend(self.generate_beam(beam))
                cmds.append("")

        return cmds

    def generate_pile(self, pile_def):
        """
        生成单根桩的 FLAC3D structure pile 命令。

        :param pile_def: dict with keys:
            id, center_x, center_y, z_bottom, z_top, radius
        :return: 命令字符串列表
        """
        cfg = self.elem_config.get('pile', {})
        sid = self._alloc_id()

        cx = pile_def['center_x']
        cy = pile_def['center_y']
        z_bot = pile_def['z_bottom']
        z_top = pile_def['z_top']
        radius = pile_def['radius']
        pile_id = pile_def.get('id', f'pile_{sid}')

        if radius <= 0:
            raise ValueError(f"Pile '{pile_id}' radius must be positive, got {radius}")
        if z_top <= z_bot:
            raise ValueError(
                f"Pile '{pile_id}' top elevation must be above bottom elevation, "
                f"got z_bottom={z_bot}, z_top={z_top}"
            )

        # 段数
        segments = cfg.get('segments', 20)

        use_schema_radius = cfg.get('derive_section_from_radius', True)

        # 截面参数：默认根据 schema 半径推导，必要时允许 config 覆盖
        derived_area = math.pi * radius ** 2
        derived_perimeter = 2 * math.pi * radius
        # 圆形截面惯性矩 I = pi*r^4/4
        derived_moi = math.pi * radius ** 4 / 4.0
        # 极惯性矩 J = pi*r^4/2
        derived_polar_moi = math.pi * radius ** 4 / 2.0

        if use_schema_radius:
            area = derived_area
            perimeter = derived_perimeter
            moi = derived_moi
            polar_moi = derived_polar_moi
        else:
            area = cfg.get('cross_section_area', derived_area)
            perimeter = cfg.get('perimeter', derived_perimeter)
            moi = cfg.get('moi', derived_moi)
            polar_moi = cfg.get('polar_moi', derived_polar_moi)

        young = cfg.get('young', 3e10)
        poisson = cfg.get('poisson', 0.2)

        # 耦合弹簧参数
        k_n = cfg.get('coupling_stiffness_normal', 1e8)
        k_s = cfg.get('coupling_stiffness_shear', 1e8)
        c_cohesion = cfg.get('coupling_cohesion', 0)
        c_friction = cfg.get('coupling_friction', 30.0)

        cmds = [
            f"; Pile: {pile_id} at ({cx:.3f}, {cy:.3f}), z=[{z_bot:.3f}, {z_top:.3f}], R={radius:.3f}m",
            f"structure pile create by-line ({self._fmt_num(cx)},{self._fmt_num(cy)},{self._fmt_num(z_bot)}) "
            f"({self._fmt_num(cx)},{self._fmt_num(cy)},{self._fmt_num(z_top)}) segments {segments} id {sid}",
            f"structure pile property young {self._fmt_num(young)} poisson {self._fmt_num(poisson)} "
            f"cross-sectional-area {self._fmt_num(area)} "
            f"moi-y {self._fmt_num(moi)} moi-z {self._fmt_num(moi)} "
            f"moi-polar {self._fmt_num(polar_moi)} perimeter {self._fmt_num(perimeter)} "
            f"coupling-stiffness-normal {self._fmt_num(k_n)} "
            f"coupling-stiffness-shear {self._fmt_num(k_s)} "
            f"coupling-cohesion-normal {self._fmt_num(c_cohesion)} "
            f"coupling-cohesion-shear {self._fmt_num(c_cohesion)} "
            f"coupling-friction-normal {self._fmt_num(c_friction)} "
            f"coupling-friction-shear {self._fmt_num(c_friction)} "
            f"range id {sid}",
            f"; Group pile for post-processing",
            f"structure node group '{pile_id}' range id {sid}",
        ]

        return cmds

    def generate_cable(self, cable_def):
        """
        生成单根锚索的 FLAC3D structure cable 命令。

        :param cable_def: dict with keys:
            id, start (x,y,z), end (x,y,z), radius (or area)
        :return: 命令字符串列表
        """
        cfg = self.elem_config.get('cable', {})
        sid = self._alloc_id()

        sx, sy, sz = cable_def['start']
        ex, ey, ez = cable_def['end']
        cable_id = cable_def.get('id', f'cable_{sid}')

        if self._segment_length(cable_def['start'], cable_def['end']) <= 0:
            raise ValueError(f"Cable '{cable_id}' start and end must be different")

        segments = cfg.get('segments', 10)
        young = cfg.get('young', 2e11)  # 钢材默认
        if 'area' in cable_def:
            area = cable_def['area']
        elif 'radius' in cable_def:
            area = math.pi * cable_def['radius'] ** 2
        else:
            area = cfg.get('cross_section_area', 0.001)
        if area <= 0:
            raise ValueError(f"Cable '{cable_id}' cross-sectional area must be positive, got {area}")

        # 锚固参数
        grout_stiffness = cfg.get('grout_stiffness', 1e8)
        grout_cohesion = cfg.get('grout_cohesion', 1e5)
        grout_friction = cfg.get('grout_friction', 30.0)
        grout_perimeter = cable_def.get('grout_perimeter', cfg.get('grout_perimeter', 0.2))

        # 预应力
        pretension = cable_def.get('pretension', cfg.get('pretension', 0))

        cmds = [
            f"; Cable: {cable_id}",
            f"structure cable create by-line ({self._fmt_num(sx)},{self._fmt_num(sy)},{self._fmt_num(sz)}) "
            f"({self._fmt_num(ex)},{self._fmt_num(ey)},{self._fmt_num(ez)}) segments {segments} id {sid}",
            f"structure cable property young {self._fmt_num(young)} "
            f"cross-sectional-area {self._fmt_num(area)} "
            f"grout-stiffness {self._fmt_num(grout_stiffness)} "
            f"grout-cohesion {self._fmt_num(grout_cohesion)} "
            f"grout-friction {self._fmt_num(grout_friction)} "
            f"grout-perimeter {self._fmt_num(grout_perimeter)} "
            f"range id {sid}",
        ]

        if pretension > 0:
            cmds.append(
                f"structure cable apply tension value {self._fmt_num(pretension)} range id {sid}"
            )

        cmds.append(f"structure node group '{cable_id}' range id {sid}")

        return cmds

    def generate_beam(self, beam_def):
        """
        生成单根梁的 FLAC3D structure beam 命令。

        :param beam_def: dict with keys:
            id, start (x,y,z), end (x,y,z), cross-section params
        :return: 命令字符串列表
        """
        cfg = self.elem_config.get('beam', {})
        sid = self._alloc_id()

        sx, sy, sz = beam_def['start']
        ex, ey, ez = beam_def['end']
        beam_id = beam_def.get('id', f'beam_{sid}')

        if self._segment_length(beam_def['start'], beam_def['end']) <= 0:
            raise ValueError(f"Beam '{beam_id}' start and end must be different")

        segments = cfg.get('segments', 10)
        young = beam_def.get('young', cfg.get('young', 3e10))
        poisson = beam_def.get('poisson', cfg.get('poisson', 0.2))

        if 'radius' in beam_def:
            derived_area = math.pi * beam_def['radius'] ** 2
            derived_moi = math.pi * beam_def['radius'] ** 4 / 4.0
            derived_polar_moi = math.pi * beam_def['radius'] ** 4 / 2.0
        else:
            derived_area = cfg.get('cross_section_area', 0.25)
            derived_moi = cfg.get('moi_y', cfg.get('moi', 0.005))
            derived_polar_moi = cfg.get('moi_polar', cfg.get('polar_moi', 0.01))

        area = beam_def.get('area', cfg.get('cross_section_area', derived_area) if 'radius' not in beam_def else derived_area)
        moi_y = beam_def.get('moi_y', cfg.get('moi_y', cfg.get('moi', derived_moi)) if 'radius' not in beam_def else derived_moi)
        moi_z = beam_def.get('moi_z', cfg.get('moi_z', cfg.get('moi', derived_moi)) if 'radius' not in beam_def else derived_moi)
        polar_moi = beam_def.get('moi_polar', cfg.get('moi_polar', cfg.get('polar_moi', derived_polar_moi)) if 'radius' not in beam_def else derived_polar_moi)

        if area <= 0 or moi_y <= 0 or moi_z <= 0 or polar_moi < 0:
            raise ValueError(f"Beam '{beam_id}' has invalid section properties")

        cmds = [
            f"; Beam: {beam_id}",
            f"structure beam create by-line ({self._fmt_num(sx)},{self._fmt_num(sy)},{self._fmt_num(sz)}) "
            f"({self._fmt_num(ex)},{self._fmt_num(ey)},{self._fmt_num(ez)}) segments {segments} id {sid}",
            f"structure beam property young {self._fmt_num(young)} poisson {self._fmt_num(poisson)} "
            f"cross-sectional-area {self._fmt_num(area)} "
            f"moi-y {self._fmt_num(moi_y)} moi-z {self._fmt_num(moi_z)} "
            f"moi-polar {self._fmt_num(polar_moi)} "
            f"range id {sid}",
            f"structure node group '{beam_id}' range id {sid}",
        ]

        return cmds
