"""
GmshMesher: Path B 实体建模 — 使用 Gmsh OpenCASCADE 内核完成
地质体+结构体的几何构建、布尔运算和网格划分。

流程：
  1. 从地形 STL 构建封闭地质体体积
  2. 从 schema 构建结构体 OCC 实体
  3. 执行 schema 内部布尔运算（结构体自身的 union/difference）
  4. fragment 联合布尔（地质体 vs 结构体 → 共形分割）
  5. 按来源和深度赋 physical group
  6. 设置 mesh size field（结构附近加密）
  7. 生成四面体网格
  8. 导出 → mesh_converter 转 .f3grid
"""

import os
import numpy as np

try:
    import gmsh
except ImportError:
    gmsh = None

try:
    import trimesh
except ImportError:
    trimesh = None


class GmshMesher:
    """Gmsh OpenCASCADE 内核的联合建模与网格生成器。"""

    def __init__(self, stl_path, bounds, schema_primitives, schema_operations,
                 layers_config, gmsh_config, structure_final_ids=None):
        """
        :param stl_path: 地形 STL 文件路径
        :param bounds: (xmin, xmax, ymin, ymax, zmin, zmax) 地形包围盒
        :param schema_primitives: 解析后的 primitives 列表
        :param schema_operations: 解析后的 operations 列表
        :param layers_config: config.LAYERS 地层配置
        :param gmsh_config: dict with keys:
            mesh_size_terrain, mesh_size_structure, algorithm, optimize
        :param structure_final_ids: schema outputs.final_objects 列表
        """
        if gmsh is None:
            raise ImportError("gmsh package not installed. Run: pip install gmsh")

        self.stl_path = stl_path
        self.bounds = bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)
        self.primitives = schema_primitives
        self.operations = schema_operations
        self.layers_config = layers_config
        self.structure_final_ids = structure_final_ids or []

        self.mesh_size_terrain = gmsh_config.get('mesh_size_terrain', 2.0)
        self.mesh_size_structure = gmsh_config.get('mesh_size_structure', 0.5)
        self.mesh_algorithm = gmsh_config.get('algorithm', 6)
        self.optimize = gmsh_config.get('optimize', True)

        # OCC dimTag 映射
        self._prim_tags = {}      # primitive_id -> (dim, tag)
        self._terrain_volumes = []  # 地质体体积 dimTags
        self._structure_volumes = []  # 结构体体积 dimTags
        self._fragment_map = {}   # 映射 fragment 后的体积到源标识

        # 网格数据（generate_mesh 后可用）
        self.nodes = None         # (N, 3) 节点坐标
        self.node_ids = None      # (N,) 节点编号
        self.elements = None      # (M, 4) 四面体连接
        self.element_ids = None   # (M,) 单元编号
        self.element_groups = None  # (M,) 分组名称

    def run(self, output_dir):
        """
        执行完整的建模-网格生成流程。

        :param output_dir: 输出目录
        :return: .f3grid 文件路径
        """
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add("SlopeRA3D_SSI")

        try:
            print("[GmshMesher] Building terrain volume...")
            self.build_terrain_volume()

            print("[GmshMesher] Building structure solids...")
            self.build_structure_solids()

            print("[GmshMesher] Applying schema boolean operations...")
            self.apply_schema_booleans()

            print("[GmshMesher] Fragmenting (conforming boolean)...")
            self.fragment_all()

            print("[GmshMesher] Assigning physical groups...")
            self.assign_groups()

            print("[GmshMesher] Setting mesh sizes...")
            self.set_mesh_sizes()

            print("[GmshMesher] Generating 3D mesh...")
            self.generate_mesh()

            print("[GmshMesher] Exporting mesh data...")
            f3grid_path = self.export(output_dir)

            return f3grid_path
        finally:
            gmsh.finalize()

    def build_terrain_volume(self):
        """
        从地形 STL 构建封闭地质体体积。

        策略：构建一个 bounding box，顶面用地形 STL 切割。
        1. 创建底部 box（从 z_bottom 到 z_max_terrain + margin）
        2. 导入 STL 作为表面
        3. 将 STL 表面挤出为切割体
        4. 用 cut 操作从 box 中减去地形以上的部分

        备选策略（更稳健）：直接构建 box 作为地质体，
        后续在 FLAC3D 中用 from-topography 处理顶面。
        """
        xmin, xmax, ymin, ymax, zmin_topo, zmax_topo = self.bounds
        bot_offset = 10.0  # 与 config.MODEL_BOT_OFFSET 一致

        z_bottom = zmin_topo - bot_offset
        z_top_cap = zmax_topo + 5.0  # 留余量

        # 方法：构建完整 box，然后用 STL 表面分割
        # 先尝试直接导入 STL，如果失败则退回到纯 box 模式

        # 创建包围盒体积
        margin = 0.1
        box_tag = gmsh.model.occ.addBox(
            xmin - margin, ymin - margin, z_bottom,
            (xmax - xmin) + 2 * margin,
            (ymax - ymin) + 2 * margin,
            z_top_cap - z_bottom
        )

        terrain_imported = False
        try:
            # 尝试导入 STL 作为 OCC shape
            stl_shapes = gmsh.model.occ.importShapes(self.stl_path)
            if stl_shapes:
                # STL 导入为 surface -> 需要转为切割体
                # 构建一个从 STL 面到 z_top_cap 的 "帽子" 体积用于 cut
                # 这种方法复杂且不稳定，改用分层 box 策略
                terrain_imported = True
                print(f"  STL imported: {len(stl_shapes)} shapes")

                # 创建从地形面向上延伸的切割体
                cap_box = gmsh.model.occ.addBox(
                    xmin - margin - 1, ymin - margin - 1, zmax_topo,
                    (xmax - xmin) + 2 * margin + 2,
                    (ymax - ymin) + 2 * margin + 2,
                    z_top_cap - zmax_topo + 1
                )

                # 用 STL 表面和 cap_box 进行 fragment
                # 注意：STL 表面可能不是 solid，直接 cut 可能失败
                # 这里我们用更稳健的策略：保留完整 box，后续交给 FLAC3D
                # 处理 topography 适配

                # 清理临时 cap_box
                gmsh.model.occ.remove([(3, cap_box)])
                # 清理导入的 STL shapes
                for dim, tag in stl_shapes:
                    try:
                        gmsh.model.occ.remove([(dim, tag)])
                    except Exception:
                        pass

                terrain_imported = False  # 回退到 box 模式
                print("  STL boolean cut not reliable, using box terrain volume.")

        except Exception as e:
            print(f"  STL import failed ({e}), using box terrain volume.")
            terrain_imported = False

        if not terrain_imported:
            # 使用纯 box 作为地质体，顶面平齐 z_max_topo
            # 后续在 FLAC3D .dat 中仍然用 from-topography 调整顶面
            # 但对于 Path B，我们重新创建 box 到 z_max_topo
            gmsh.model.occ.remove([(3, box_tag)])
            box_tag = gmsh.model.occ.addBox(
                xmin - margin, ymin - margin, z_bottom,
                (xmax - xmin) + 2 * margin,
                (ymax - ymin) + 2 * margin,
                zmax_topo - z_bottom
            )

        gmsh.model.occ.synchronize()
        self._terrain_volumes = [(3, box_tag)]
        print(f"  Terrain volume: tag={box_tag}, "
              f"z=[{z_bottom:.1f}, {zmax_topo:.1f}]")

    def build_structure_solids(self):
        """从 schema primitives 创建 Gmsh OCC 实体。"""
        for prim in self.primitives:
            prim_id = prim['id']
            ptype = prim['type']
            tag = None

            if ptype == 'box':
                ox, oy, oz = prim['origin']
                dx, dy, dz = prim['size']
                tag = gmsh.model.occ.addBox(ox, oy, oz, dx, dy, dz)

            elif ptype == 'cylinder':
                cx, cy, cz = prim['center']
                radius = prim['radius']
                height = prim['height']
                # Gmsh addCylinder: (x, y, z, dx, dy, dz, r)
                # z 方向挤出
                tag = gmsh.model.occ.addCylinder(cx, cy, cz, 0, 0, height, radius)

            elif ptype == 'polyline_extrude':
                tag = self._build_polyline_extrude(prim)

            if tag is not None:
                self._prim_tags[prim_id] = (3, tag)
                print(f"  Created {ptype}: {prim_id} -> tag={tag}")
            else:
                print(f"  [Warning] Failed to create {ptype}: {prim_id}")

        gmsh.model.occ.synchronize()

    def _build_polyline_extrude(self, prim):
        """构建多边形挤出体。"""
        profile = prim.get('profile', [])
        if len(profile) < 3:
            return None

        z0 = prim.get('z0', 0)
        height = prim['height']

        # 创建线段
        points = []
        for pt in profile:
            p = gmsh.model.occ.addPoint(pt[0], pt[1], z0)
            points.append(p)

        # 闭合
        lines = []
        for i in range(len(points)):
            j = (i + 1) % len(points)
            line = gmsh.model.occ.addLine(points[i], points[j])
            lines.append(line)

        # 创建 wire -> surface -> extrude
        wire = gmsh.model.occ.addCurveLoop(lines)
        surface = gmsh.model.occ.addPlaneSurface([wire])
        extruded = gmsh.model.occ.extrude([(2, surface)], 0, 0, height)

        # 找到生成的 volume
        for dim, tag in extruded:
            if dim == 3:
                return tag

        return None

    def apply_schema_booleans(self):
        """执行 schema 中定义的布尔运算（结构体自身之间的运算）。"""
        for op in self.operations:
            op_type = op['op']
            result_id = op.get('result') or op.get('id')

            if op_type == 'boolean_union':
                input_ids = op.get('inputs', [])
                input_tags = self._resolve_tags(input_ids)
                if len(input_tags) < 2:
                    print(f"  [Warning] Union needs >=2 inputs: {result_id}")
                    continue

                result, _ = gmsh.model.occ.fuse(
                    [input_tags[0]], input_tags[1:],
                    removeObject=True, removeTool=True
                )
                if result:
                    self._prim_tags[result_id] = result[0]
                    print(f"  Union: {input_ids} -> {result_id} (tag={result[0][1]})")

            elif op_type == 'boolean_difference':
                target_id = op.get('target')
                tool_ids = op.get('tools', [])
                target_tag = self._prim_tags.get(target_id)
                tool_tags = self._resolve_tags(tool_ids)

                if target_tag is None or not tool_tags:
                    print(f"  [Warning] Difference missing target/tools: {result_id}")
                    continue

                result, _ = gmsh.model.occ.cut(
                    [target_tag], tool_tags,
                    removeObject=True, removeTool=True
                )
                if result:
                    self._prim_tags[result_id] = result[0]
                    print(f"  Difference: {target_id} - {tool_ids} -> {result_id} (tag={result[0][1]})")

            elif op_type == 'boolean_intersection':
                input_ids = op.get('inputs', [])
                input_tags = self._resolve_tags(input_ids)
                if len(input_tags) < 2:
                    print(f"  [Warning] Intersection needs >=2 inputs: {result_id}")
                    continue

                result, _ = gmsh.model.occ.intersect(
                    [input_tags[0]], input_tags[1:],
                    removeObject=True, removeTool=True
                )
                if result:
                    self._prim_tags[result_id] = result[0]
                    print(f"  Intersection: {input_ids} -> {result_id} (tag={result[0][1]})")

        gmsh.model.occ.synchronize()

        # 收集最终结构体体积
        for fid in self.structure_final_ids:
            if fid in self._prim_tags:
                self._structure_volumes.append(self._prim_tags[fid])

        # 如果没有定义 final_objects，则使用所有仍存在的 primitive tags
        if not self._structure_volumes:
            for pid, dtag in self._prim_tags.items():
                # 检查这个 tag 是否仍存在于模型中
                try:
                    bb = gmsh.model.occ.getBoundingBox(dtag[0], dtag[1])
                    self._structure_volumes.append(dtag)
                except Exception:
                    pass  # 已被布尔运算消耗

        print(f"  Structure volumes: {len(self._structure_volumes)}")

    def _resolve_tags(self, ids):
        """将 ID 列表解析为 dimTag 列表。"""
        tags = []
        for pid in ids:
            if pid in self._prim_tags:
                tags.append(self._prim_tags[pid])
            else:
                print(f"  [Warning] Reference not found: {pid}")
        return tags

    def fragment_all(self):
        """
        对地质体和结构体执行 OCC fragment 操作。
        fragment 将所有体积在交界面处分割，产生共形网格。
        """
        if not self._terrain_volumes or not self._structure_volumes:
            print("  [Warning] No terrain or structure volumes to fragment.")
            if self._terrain_volumes:
                self._fragment_map = {
                    self._terrain_volumes[0]: 'terrain'
                }
            return

        all_objects = self._terrain_volumes
        all_tools = self._structure_volumes

        result, result_map = gmsh.model.occ.fragment(
            all_objects, all_tools,
            removeObject=True, removeTool=True
        )

        gmsh.model.occ.synchronize()

        # 解析 fragment 结果：result_map[i] 对应输入 (objects + tools)[i] 的子体积
        # objects 在前，tools 在后
        n_objects = len(all_objects)

        # 标记各体积的来源
        self._fragment_map = {}
        for i, sub_volumes in enumerate(result_map):
            if i < n_objects:
                source = 'terrain'
            else:
                source = 'structure'
            for dtag in sub_volumes:
                if dtag[0] == 3:  # 只处理体积
                    self._fragment_map[dtag] = source

        # fragment 后，结构体占据的空间已从地质体中"扣除"
        # 结构体区域标记为 'structure'，剩余地质体区域标记为 'terrain'
        n_terrain = sum(1 for v in self._fragment_map.values() if v == 'terrain')
        n_struct = sum(1 for v in self._fragment_map.values() if v == 'structure')
        print(f"  Fragment result: {n_terrain} terrain + {n_struct} structure volumes")

    def assign_groups(self):
        """
        为 fragment 后的各体积分配 physical group。
        - 结构体体积 -> 'concrete'（或按 schema layer 标记）
        - 地质体体积 -> 按深度分层（top_soil, weathered_rock, bedrock）
        """
        group_id = 1

        # 结构体 group
        struct_tags = [dt for dt, src in self._fragment_map.items() if src == 'structure']
        if struct_tags:
            pg = gmsh.model.addPhysicalGroup(3, [t[1] for t in struct_tags], group_id)
            gmsh.model.setPhysicalName(3, pg, 'concrete')
            group_id += 1
            print(f"  Physical group 'concrete': {len(struct_tags)} volumes")

        # 地质体 group — 按层分配
        terrain_tags = [dt for dt, src in self._fragment_map.items() if src == 'terrain']

        if not terrain_tags:
            return

        if not self.layers_config:
            # 无分层配置，全部归为一个 group
            pg = gmsh.model.addPhysicalGroup(3, [t[1] for t in terrain_tags], group_id)
            gmsh.model.setPhysicalName(3, pg, 'soil')
            return

        # 计算每个体积的质心 z 坐标，根据到地形顶面的距离分层
        zmax_topo = self.bounds[5]  # z_max_topo

        layer_assignments = {layer['name']: [] for layer in self.layers_config}

        for dtag in terrain_tags:
            try:
                bb = gmsh.model.occ.getBoundingBox(dtag[0], dtag[1])
                # bb = (xmin, ymin, zmin, xmax, ymax, zmax)
                centroid_z = (bb[2] + bb[5]) / 2.0
                depth = zmax_topo - centroid_z  # 到地表的深度

                # 按深度判断属于哪一层
                assigned = False
                acc_thickness = 0.0
                for layer in self.layers_config:
                    if layer['thickness'] is None:
                        # 最后一层（基岩）兜底
                        layer_assignments[layer['name']].append(dtag[1])
                        assigned = True
                        break
                    acc_thickness += layer['thickness']
                    if depth <= acc_thickness:
                        layer_assignments[layer['name']].append(dtag[1])
                        assigned = True
                        break

                if not assigned:
                    # 超出所有定义层的深度，归入最后一层
                    last_layer = self.layers_config[-1]['name']
                    layer_assignments[last_layer].append(dtag[1])

            except Exception as e:
                print(f"  [Warning] Cannot get bounding box for {dtag}: {e}")
                # 归入最后一层
                last_layer = self.layers_config[-1]['name']
                layer_assignments[last_layer].append(dtag[1])

        # 创建 physical groups
        for layer_name, vol_tags in layer_assignments.items():
            if vol_tags:
                pg = gmsh.model.addPhysicalGroup(3, vol_tags, group_id)
                gmsh.model.setPhysicalName(3, pg, layer_name)
                group_id += 1
                print(f"  Physical group '{layer_name}': {len(vol_tags)} volumes")

    def set_mesh_sizes(self):
        """设置网格尺寸：结构附近加密，远处粗放。"""
        # 全局背景尺寸
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", self.mesh_size_terrain)

        # 结构体附近的尺寸场
        struct_tags = [dt for dt, src in self._fragment_map.items() if src == 'structure']

        if struct_tags:
            # 在结构体表面设置细密网格
            for dtag in struct_tags:
                # 获取体积的所有边界面
                try:
                    boundaries = gmsh.model.getBoundary([dtag], oriented=False)
                    for bdim, btag in boundaries:
                        # 获取面上所有点
                        pts = gmsh.model.getBoundary([(bdim, btag)], oriented=False)
                        for pdim, ptag in pts:
                            if pdim == 0:
                                gmsh.model.mesh.setSize([(pdim, ptag)], self.mesh_size_structure)
                except Exception:
                    pass

        # Distance field + Threshold field 实现过渡
        if struct_tags:
            try:
                # 获取结构体所有表面
                all_surfaces = []
                for dtag in struct_tags:
                    boundaries = gmsh.model.getBoundary([dtag], oriented=False)
                    all_surfaces.extend([btag for bdim, btag in boundaries if bdim == 2])

                if all_surfaces:
                    f_dist = gmsh.model.mesh.field.add("Distance")
                    gmsh.model.mesh.field.setNumbers(f_dist, "SurfacesList", all_surfaces)

                    f_thresh = gmsh.model.mesh.field.add("Threshold")
                    gmsh.model.mesh.field.setNumber(f_thresh, "InField", f_dist)
                    gmsh.model.mesh.field.setNumber(f_thresh, "SizeMin", self.mesh_size_structure)
                    gmsh.model.mesh.field.setNumber(f_thresh, "SizeMax", self.mesh_size_terrain)
                    gmsh.model.mesh.field.setNumber(f_thresh, "DistMin", 0)
                    gmsh.model.mesh.field.setNumber(f_thresh, "DistMax",
                                                     self.mesh_size_terrain * 3)

                    gmsh.model.mesh.field.setAsBackgroundMesh(f_thresh)
            except Exception as e:
                print(f"  [Warning] Size field setup failed: {e}")

        # 网格算法
        # Algorithm 值 (1=MeshAdapt, 5=Delaunay, 6=Frontal-Delaunay) 用于 2D
        # Algorithm3D 值 (1=Delaunay, 4=Frontal, 7=MMG3D, 10=HXT) 用于 3D
        gmsh.option.setNumber("Mesh.Algorithm", self.mesh_algorithm)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)  # Delaunay for 3D

    def generate_mesh(self):
        """生成 3D 四面体网格。"""
        gmsh.model.mesh.generate(3)

        if self.optimize:
            gmsh.model.mesh.optimize("Netgen")

        # 提取网格数据
        self._extract_mesh_data()

        # 统计
        n_nodes = len(self.node_ids) if self.node_ids is not None else 0
        n_elements = len(self.element_ids) if self.element_ids is not None else 0
        print(f"  Mesh: {n_nodes} nodes, {n_elements} tetrahedra")

    def _extract_mesh_data(self):
        """从 Gmsh 提取节点、单元和分组数据。"""
        # 获取所有节点
        node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
        self.node_ids = np.array(node_tags, dtype=int)
        self.nodes = np.array(node_coords).reshape(-1, 3)

        # 获取所有四面体单元 (element type 4 = 4-node tetrahedron)
        tet_type = 4
        all_element_ids = []
        all_element_conn = []
        all_element_groups = []

        # 按 physical group 遍历
        phys_groups = gmsh.model.getPhysicalGroups(dim=3)

        for dim, pg_tag in phys_groups:
            pg_name = gmsh.model.getPhysicalName(dim, pg_tag)
            entities = gmsh.model.getEntitiesForPhysicalGroup(dim, pg_tag)

            for entity_tag in entities:
                elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim, entity_tag)

                for i, etype in enumerate(elem_types):
                    if etype == tet_type:
                        e_ids = np.array(elem_tags[i], dtype=int)
                        e_conn = np.array(elem_node_tags[i], dtype=int).reshape(-1, 4)
                        all_element_ids.append(e_ids)
                        all_element_conn.append(e_conn)
                        all_element_groups.extend([pg_name] * len(e_ids))

        if all_element_ids:
            self.element_ids = np.concatenate(all_element_ids)
            self.elements = np.concatenate(all_element_conn)
            self.element_groups = np.array(all_element_groups, dtype=object)
        else:
            self.element_ids = np.array([], dtype=int)
            self.elements = np.array([], dtype=int).reshape(0, 4)
            self.element_groups = np.array([], dtype=object)

    def export(self, output_dir):
        """
        导出网格到 .f3grid 文件。

        :param output_dir: 输出目录
        :return: .f3grid 文件路径
        """
        from src.mesh_converter import MeshConverter

        converter = MeshConverter(
            node_ids=self.node_ids,
            nodes=self.nodes,
            element_ids=self.element_ids,
            elements=self.elements,
            element_groups=self.element_groups,
            layers_slot='layers'
        )

        f3grid_path = os.path.join(output_dir, 'model_mesh.f3grid')
        converter.write_f3grid(f3grid_path)

        return f3grid_path
