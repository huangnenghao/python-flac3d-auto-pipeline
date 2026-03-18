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

        # 全局 link attach（让结构元素与 zone 网格耦合）
        cmds.append("; --- Attach structure links to zones ---")
        cmds.append("structure link attach slave zone")

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

        # 段数
        segments = cfg.get('segments', 20)

        # 截面参数：如果 config 中有，使用 config；否则从 radius 计算
        area = cfg.get('cross_section_area', math.pi * radius ** 2)
        perimeter = cfg.get('perimeter', 2 * math.pi * radius)
        # 圆形截面惯性矩 I = pi*r^4/4
        moi = cfg.get('moi', math.pi * radius ** 4 / 4.0)
        # 极惯性矩 J = pi*r^4/2
        polar_moi = cfg.get('polar_moi', math.pi * radius ** 4 / 2.0)

        young = cfg.get('young', 3e10)

        # 耦合弹簧参数
        k_n = cfg.get('coupling_stiffness_normal', 1e8)
        k_s = cfg.get('coupling_stiffness_shear', 1e8)
        c_cohesion = cfg.get('coupling_cohesion', 0)
        c_friction = cfg.get('coupling_friction', 30.0)

        cmds = [
            f"; Pile: {pile_id} at ({cx:.3f}, {cy:.3f}), z=[{z_bot:.3f}, {z_top:.3f}], R={radius:.3f}m",
            f"structure pile create by-line ({cx},{cy},{z_bot}) ({cx},{cy},{z_top}) segments {segments} id {sid}",
            f"structure pile property young {young} cross-section-area {area} "
            f"moi {moi} perimeter {perimeter} "
            f"coupling-stiffness-normal {k_n} coupling-stiffness-shear {k_s} "
            f"coupling-cohesion {c_cohesion} coupling-friction {c_friction} "
            f"range id {sid}",
            f"structure pile property polar-moi {polar_moi} range id {sid}",
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

        segments = cfg.get('segments', 10)
        young = cfg.get('young', 2e11)  # 钢材默认
        area = cable_def.get('area', cfg.get('cross_section_area', 0.001))  # m^2

        # 锚固参数
        grout_stiffness = cfg.get('grout_stiffness', 1e8)
        grout_cohesion = cfg.get('grout_cohesion', 1e5)
        grout_friction = cfg.get('grout_friction', 30.0)
        grout_perimeter = cfg.get('grout_perimeter', 0.2)

        # 预应力
        pretension = cable_def.get('pretension', cfg.get('pretension', 0))

        cmds = [
            f"; Cable: {cable_id}",
            f"structure cable create by-line ({sx},{sy},{sz}) ({ex},{ey},{ez}) segments {segments} id {sid}",
            f"structure cable property young {young} cross-section-area {area} "
            f"grout-stiffness {grout_stiffness} grout-cohesion {grout_cohesion} "
            f"grout-friction {grout_friction} grout-perimeter {grout_perimeter} "
            f"range id {sid}",
        ]

        if pretension > 0:
            cmds.append(f"structure cable apply tension {pretension} range id {sid}")

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

        segments = cfg.get('segments', 10)
        young = cfg.get('young', 3e10)
        poisson = cfg.get('poisson', 0.2)
        area = cfg.get('cross_section_area', 0.25)  # m^2
        moi = cfg.get('moi', 0.005)  # m^4
        polar_moi = cfg.get('polar_moi', 0.01)

        cmds = [
            f"; Beam: {beam_id}",
            f"structure beam create by-line ({sx},{sy},{sz}) ({ex},{ey},{ez}) segments {segments} id {sid}",
            f"structure beam property young {young} poisson {poisson} "
            f"cross-section-area {area} moi {moi} polar-moi {polar_moi} "
            f"range id {sid}",
            f"structure node group '{beam_id}' range id {sid}",
        ]

        return cmds
