"""
SSI Pipeline 端到端测试 (不调用 FLAC3D)
验证: TIF加载 → STL生成 → Schema解析 → Path A 命令生成
"""
import os
import sys
import math
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import config

# 强制配置
config.SSI_ENABLED = True
config.SSI_PATH = 'A'

PROJECT = 'test'
dirs = config.get_project_dirs(PROJECT)
input_dir = dirs['input']
output_dir = dirs['output']
config.OUTPUT_DIR = output_dir
os.makedirs(output_dir, exist_ok=True)

tif_path = os.path.join(input_dir, 'DEM.tif')
stl_path = os.path.join(output_dir, 'terrain_surface.stl')
schema_path = os.path.join(input_dir, 'structure_schema.json')
mixed_schema_path = os.path.join(input_dir, 'structure_schema_path_a_mixed.json')

print("=" * 60)
print("SSI Pipeline Test (Path A)")
print("=" * 60)

# STEP 1
print("\n>>> STEP 1: Loading TIF...")
from src.tif_loader import TifLoader
loader = TifLoader(tif_path)
x, y, z = loader.load_data(downsample_factor=config.DOWNSAMPLE_FACTOR)
print(f"  Grid shape: {z.shape}")
print(f"  Z range: [{np.nanmin(z):.1f}, {np.nanmax(z):.1f}]")

# STEP 2
print("\n>>> STEP 2: Building STL...")
from src.surface_builder import SurfaceBuilder
builder = SurfaceBuilder(x, y, z)
builder.build_mesh()
terrain_grid_transformed = builder.get_transformed_grids()
builder.export_stl(stl_path)

bounds = (
    builder.mesh.bounds[0][0], builder.mesh.bounds[1][0],
    builder.mesh.bounds[0][1], builder.mesh.bounds[1][1],
    builder.mesh.bounds[0][2], builder.mesh.bounds[1][2],
)
print(f"  PCA angle: {np.degrees(builder.pca_angle):.2f} deg")
print(f"  Centroid: {builder.centroid}")
print(f"  Bounds: X[{bounds[0]:.1f},{bounds[1]:.1f}] "
      f"Y[{bounds[2]:.1f},{bounds[3]:.1f}] "
      f"Z[{bounds[4]:.1f},{bounds[5]:.1f}]")

# STEP 2.5
print("\n>>> STEP 2.5: Schema Parsing + Path A...")
from src.schema_parser import StructureSchemaParser
parser = StructureSchemaParser()
parser.load(schema_path)
print(f"  Loaded: {len(parser.get_primitives())} primitives")

parser.normalize_units(target_unit='m')
parser.apply_transform(builder.pca_angle, builder.centroid)
parser.validate()
print("  Validation: PASSED")

classified = parser.classify_for_path_a()
n_piles = len(classified.get('piles', []))
unsupported = classified.get('unsupported', [])
print(f"  Classified: {n_piles} piles")
print(f"  Unsupported finals: {unsupported}")

assert n_piles == 5, f"Expected 5 piles, got {n_piles}"
assert not unsupported, f"Expected no unsupported final objects, got {unsupported}"
assert all(p['z_top'] > p['z_bottom'] for p in classified['piles']), "Pile top must be above bottom"
assert all(p['radius'] > 0 for p in classified['piles']), "Pile radius must be positive"
assert all('top_x' in p and 'top_y' in p for p in classified['piles']), "Pile endpoints should preserve top XY"

for p in classified['piles']:
    print(f"    {p['id']}: center=({p['center_x']:.1f}, "
          f"{p['center_y']:.1f}), "
          f"z=[{p['z_bottom']:.1f}, {p['z_top']:.1f}], "
          f"r={p['radius']:.2f}")

from src.structure_elements import StructureElementGenerator
from src.flac3d_runner import Flac3DRunner
from src.path_a_geometry import validate_path_a_geometry
from src.path_b_geometry import validate_path_b_schema
gen = StructureElementGenerator(config)
cmds = gen.generate_all(classified)
pile_cmd = next(cmd for cmd in cmds if cmd.startswith("structure pile property "))
expected_area = math.pi * classified['piles'][0]['radius'] ** 2
expected_moi = math.pi * classified['piles'][0]['radius'] ** 4 / 4.0
expected_polar_moi = math.pi * classified['piles'][0]['radius'] ** 4 / 2.0

assert "cross-sectional-area" in pile_cmd
assert "moi-y" in pile_cmd and "moi-z" in pile_cmd and "moi-polar" in pile_cmd
assert "coupling-cohesion-normal" in pile_cmd and "coupling-cohesion-shear" in pile_cmd
assert "coupling-friction-normal" in pile_cmd and "coupling-friction-shear" in pile_cmd
assert f"cross-sectional-area {expected_area:.12g}" in pile_cmd
assert f"moi-y {expected_moi:.12g}" in pile_cmd
assert f"moi-polar {expected_polar_moi:.12g}" in pile_cmd

print(f"\n  Generated {len(cmds)} FLAC3D commands:")
for cmd in cmds[:15]:
    print(f"    {cmd}")
if len(cmds) > 15:
    print(f"    ... ({len(cmds) - 15} more)")

print("\n" + "=" * 60)
print("TEST PASSED - Path A pipeline OK (STEP 1 -> 2 -> 2.5)")
print("=" * 60)

print("\n\n" + "=" * 60)
print("SSI Pipeline Test (Path A - Mixed Members)")
print("=" * 60)

parser_mixed = StructureSchemaParser()
parser_mixed.load(mixed_schema_path)
parser_mixed.normalize_units(target_unit='m')
parser_mixed.apply_transform(builder.pca_angle, builder.centroid)
parser_mixed.validate()

classified_mixed = parser_mixed.classify_for_path_a()
n_piles_mixed = len(classified_mixed.get('piles', []))
n_cables_mixed = len(classified_mixed.get('cables', []))
n_beams_mixed = len(classified_mixed.get('beams', []))
unsupported_mixed = classified_mixed.get('unsupported', [])
geometry_errors_mixed = validate_path_a_geometry(classified_mixed, builder.mesh.vertices, bounds)

print(f"  Classified: piles={n_piles_mixed}, cables={n_cables_mixed}, beams={n_beams_mixed}")
print(f"  Unsupported finals: {unsupported_mixed}")

assert n_piles_mixed == 5, f"Expected 5 piles, got {n_piles_mixed}"
assert n_cables_mixed == 1, f"Expected 1 cable, got {n_cables_mixed}"
assert n_beams_mixed == 1, f"Expected 1 beam, got {n_beams_mixed}"
assert not unsupported_mixed, f"Expected no unsupported final objects, got {unsupported_mixed}"
assert not geometry_errors_mixed, f"Expected embedded cable geometry, got {geometry_errors_mixed}"

invalid_slanted_pile = {
    'piles': [{
        'id': 'pile_slanted',
        'center_x': classified_mixed['piles'][0]['center_x'],
        'center_y': classified_mixed['piles'][0]['center_y'],
        'top_x': classified_mixed['piles'][0]['center_x'] + 1.0,
        'top_y': classified_mixed['piles'][0]['center_y'],
        'z_bottom': classified_mixed['piles'][0]['z_bottom'],
        'z_top': classified_mixed['piles'][0]['z_top'],
        'radius': classified_mixed['piles'][0]['radius'],
    }],
    'cables': [],
    'beams': [],
}
errors_slanted_pile = validate_path_a_geometry(invalid_slanted_pile, builder.mesh.vertices, bounds)
assert any("vertical" in err for err in errors_slanted_pile), errors_slanted_pile

invalid_cable = {
    'piles': classified_mixed['piles'],
    'cables': [{
        'id': 'cable_outside',
        'start': [bounds[1] + 5.0, bounds[3] + 5.0, bounds[5] + 2.0],
        'end': [bounds[1] + 15.0, bounds[3] + 10.0, bounds[5] + 1.0],
    }],
    'beams': [],
}
errors_invalid_cable = validate_path_a_geometry(invalid_cable, builder.mesh.vertices, bounds)
assert any("does not intersect" in err or "outside terrain XY bounds" in err for err in errors_invalid_cable), errors_invalid_cable

invalid_beam = {
    'piles': classified_mixed['piles'],
    'cables': [],
    'beams': [{
        'id': 'beam_far',
        'start': [bounds[0] + 1.0, bounds[2] + 1.0, bounds[5] - 1.0],
        'end': [bounds[0] + 4.0, bounds[2] + 1.0, bounds[5] - 1.0],
    }],
}
errors_invalid_beam = validate_path_a_geometry(invalid_beam, builder.mesh.vertices, bounds)
assert any("pile head" in err for err in errors_invalid_beam), errors_invalid_beam

mixed_cmds = gen.generate_all(classified_mixed)
cable_cmd = next(cmd for cmd in mixed_cmds if cmd.startswith("structure cable property "))
beam_cmd = next(cmd for cmd in mixed_cmds if cmd.startswith("structure beam property "))
cable_apply_cmd = next(cmd for cmd in mixed_cmds if cmd.startswith("structure cable apply tension "))
release_cmds = Flac3DRunner()._build_structure_release_cmds(mixed_cmds)

expected_cable_area = math.pi * classified_mixed['cables'][0]['radius'] ** 2
expected_beam_area = math.pi * classified_mixed['beams'][0]['radius'] ** 2
expected_beam_moi = math.pi * classified_mixed['beams'][0]['radius'] ** 4 / 4.0
expected_beam_polar_moi = math.pi * classified_mixed['beams'][0]['radius'] ** 4 / 2.0

assert "cross-sectional-area" in cable_cmd
assert "grout-stiffness" in cable_cmd and "grout-cohesion" in cable_cmd
assert f"cross-sectional-area {expected_cable_area:.12g}" in cable_cmd
assert "value" in cable_apply_cmd
assert "100000" in cable_apply_cmd
assert len(release_cmds) == 1, release_cmds
assert release_cmds[0].startswith("structure cable apply tension active off range id "), release_cmds

assert "cross-sectional-area" in beam_cmd
assert "moi-y" in beam_cmd and "moi-z" in beam_cmd and "moi-polar" in beam_cmd
assert f"cross-sectional-area {expected_beam_area:.12g}" in beam_cmd
assert f"moi-y {expected_beam_moi:.12g}" in beam_cmd
assert f"moi-polar {expected_beam_polar_moi:.12g}" in beam_cmd

print(f"  Generated {len(mixed_cmds)} mixed Path A commands")
for cmd in mixed_cmds[:20]:
    print(f"    {cmd}")
if len(mixed_cmds) > 20:
    print(f"    ... ({len(mixed_cmds) - 20} more)")

# ============================================================
# Path B 测试: Gmsh 实体建模 + 网格转换
# ============================================================
try:
    print("\n\n" + "=" * 60)
    print("SSI Pipeline Test (Path B - Gmsh)")
    print("=" * 60)

    parser_b = StructureSchemaParser()
    parser_b.load(schema_path)
    parser_b.normalize_units(target_unit='m')
    parser_b.apply_transform(builder.pca_angle, builder.centroid)
    primitives, operations = parser_b.parse()
    final_ids = parser_b.get_structure_ids()
    path_b_errors, path_b_warnings = validate_path_b_schema(primitives, operations, final_ids)

    print(f"  Primitives: {len(primitives)}, Operations: {len(operations)}")
    print(f"  Final IDs: {final_ids}")
    print(f"  Path B warnings: {path_b_warnings}")
    assert not path_b_errors, f"Expected Path B schema to be supported, got {path_b_errors}"

    parser_b_mixed = StructureSchemaParser()
    parser_b_mixed.load(mixed_schema_path)
    parser_b_mixed.normalize_units(target_unit='m')
    parser_b_mixed.apply_transform(builder.pca_angle, builder.centroid)
    primitives_mixed_b, operations_mixed_b = parser_b_mixed.parse()
    final_ids_mixed_b = parser_b_mixed.get_structure_ids()
    path_b_errors_mixed, _ = validate_path_b_schema(primitives_mixed_b, operations_mixed_b, final_ids_mixed_b)
    assert any("does not support 1D beam/cable members" in err for err in path_b_errors_mixed), path_b_errors_mixed

    print("\n>>> Initializing GmshMesher...")
    from src.gmsh_mesher import GmshMesher

    gmsh_config = {
        'mesh_size_terrain': getattr(config, 'GMSH_MESH_SIZE_TERRAIN', 2.0),
        'mesh_size_structure': getattr(config, 'GMSH_MESH_SIZE_STRUCTURE', 0.5),
        'algorithm': getattr(config, 'GMSH_MESH_ALGORITHM', 6),
        'optimize': getattr(config, 'GMSH_OPTIMIZE_QUALITY', True),
        'terrain_grid_max_points': getattr(config, 'GMSH_TERRAIN_GRID_MAX_POINTS', 5000),
        'structure_dist_min': getattr(config, 'GMSH_STRUCTURE_DIST_MIN', 0.0),
        'structure_dist_max': getattr(config, 'GMSH_STRUCTURE_DIST_MAX', 2.0),
    }

    mesher = GmshMesher(
        stl_path=stl_path,
        bounds=bounds,
        schema_primitives=primitives,
        schema_operations=operations,
        layers_config=getattr(config, 'LAYERS', []),
        gmsh_config=gmsh_config,
        structure_final_ids=final_ids,
        terrain_grid=terrain_grid_transformed,
    )

    print(">>> Running Gmsh pipeline...")
    f3grid_path = mesher.run(output_dir)

    print(f"\n  Output: {f3grid_path}")
    print(f"  File exists: {os.path.exists(f3grid_path)}")
    if os.path.exists(f3grid_path):
        size_kb = os.path.getsize(f3grid_path) / 1024
        print(f"  File size: {size_kb:.1f} KB")

    debug_info = mesher.debug_info
    print(f"  Terrain mode: {debug_info['terrain_volume_mode']}")
    print(f"  Fragment counts: {debug_info['fragment_counts']}")
    print(f"  Physical groups: {debug_info['physical_groups']}")
    assert debug_info['terrain_volume_mode'] == 'terrain_grid', debug_info
    assert debug_info['fragment_counts']['terrain'] > 0, debug_info
    assert debug_info['fragment_counts']['structure'] > 0, debug_info
    assert debug_info['physical_groups'].get('concrete', 0) > 0, debug_info
    layer_names = [layer['name'] for layer in getattr(config, 'LAYERS', [])]
    assert any(debug_info['physical_groups'].get(name, 0) > 0 for name in layer_names), debug_info
    assert mesher.element_groups is not None and len(mesher.element_groups) > 0
    assert 'concrete' in set(mesher.element_groups.tolist()), set(mesher.element_groups.tolist())

    print("\n" + "=" * 60)
    print("TEST PASSED - Path B pipeline OK")
    print("=" * 60)
except ModuleNotFoundError as e:
    print(f"\n[Skip] Path B test skipped: {e}")
