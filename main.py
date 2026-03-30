import argparse
import os
import shutil
import traceback
import numpy as np
import config
import tkinter as tk
from tkinter import filedialog
from src.tif_loader import TifLoader
from src.surface_builder import SurfaceBuilder
from src.flac3d_runner import Flac3DRunner


def select_tif_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select GeoTIFF File",
        filetypes=[("GeoTIFF files", "*.tif *.tiff"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tif-path")
    parser.add_argument("--project-name")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--run-reliability", action="store_true")
    parser.add_argument("--skip-reliability", action="store_true")
    return parser.parse_args(argv)


def resolve_runtime_options(args):
    non_interactive = args.non_interactive or getattr(config, 'MAIN_NON_INTERACTIVE', False)
    tif_path = args.tif_path or getattr(config, 'MAIN_TIF_PATH', None)
    project_name = args.project_name or getattr(config, 'MAIN_PROJECT_NAME', None)

    if args.run_reliability and args.skip_reliability:
        raise ValueError("Cannot set both --run-reliability and --skip-reliability")

    auto_reliability = getattr(config, 'MAIN_AUTO_START_RELIABILITY', None)
    if args.run_reliability:
        auto_reliability = True
    elif args.skip_reliability:
        auto_reliability = False

    return {
        'non_interactive': non_interactive,
        'tif_path': tif_path,
        'project_name': project_name,
        'auto_reliability': auto_reliability,
    }


def resolve_selected_tif(runtime_options):
    tif_path = runtime_options['tif_path']
    non_interactive = runtime_options['non_interactive']

    if tif_path:
        tif_path = os.path.abspath(tif_path)
        if not os.path.exists(tif_path):
            raise FileNotFoundError(f"TIF file not found: {tif_path}")
        return tif_path

    if non_interactive:
        raise ValueError("Non-interactive mode requires a TIF path via --tif-path or config.MAIN_TIF_PATH")

    print("Please select a GeoTIFF file to start analysis...")
    return select_tif_file()


def resolve_project_name(selected_tif_path, runtime_options):
    default_project_name = os.path.splitext(os.path.basename(selected_tif_path))[0]
    project_name = runtime_options['project_name']

    if project_name:
        return project_name

    if runtime_options['non_interactive']:
        return default_project_name

    project_name = input(f"Enter project name (default: {default_project_name}): ").strip()
    return project_name or default_project_name


def resolve_reliability_choice(runtime_options):
    auto_reliability = runtime_options['auto_reliability']
    if auto_reliability is not None:
        return auto_reliability
    if runtime_options['non_interactive']:
        return False
    return None


def write_path_a_commands(output_dir, structure_cmds):
    if not structure_cmds:
        return None

    commands_path = os.path.join(output_dir, 'path_a_structure_commands.dat')
    with open(commands_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(structure_cmds))
        f.write('\n')
    return commands_path


def main(argv=None):
    print("=== SlopeRA3D: TIF to FLAC3D Pipeline ===")

    args = parse_args(argv)
    runtime_options = resolve_runtime_options(args)

    selected_tif_path = resolve_selected_tif(runtime_options)
    if not selected_tif_path:
        print("[Info] No file selected. Exiting...")
        return False

    project_name = resolve_project_name(selected_tif_path, runtime_options)

    dirs = config.get_project_dirs(project_name)
    input_dir = dirs['input']
    output_dir = dirs['output']

    print(f"Current Project: {project_name}")
    print(f"Input Directory: {input_dir}")
    print(f"Output Directory: {output_dir}")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    tif_filename = os.path.basename(selected_tif_path)
    target_tif_path = os.path.join(input_dir, tif_filename)

    if os.path.abspath(selected_tif_path) != os.path.abspath(target_tif_path):
        print("Copying TIF file to project input directory...")
        try:
            shutil.copy2(selected_tif_path, target_tif_path)
            print(f"  [Success] Copied to: {target_tif_path}")
        except Exception as e:
            print(f"  [Error] Failed to copy file: {e}")
            return False
    else:
        print("  [Info] File already exists in input directory.")

    input_tif_path = target_tif_path
    output_stl_path = os.path.join(output_dir, config.STL_FILENAME)
    config.OUTPUT_DIR = output_dir

    print("\n>>> STEP 1: Loading TIF Data...")
    try:
        loader = TifLoader(input_tif_path)
        x, y, z = loader.load_data(downsample_factor=config.DOWNSAMPLE_FACTOR)
        if config.Z_SCALE != 1.0:
            print(f"  Applying Z-scale: {config.Z_SCALE}")
            z = z * config.Z_SCALE
        print("  [Success] TIF data loaded.")
    except Exception as e:
        print(f"  [Failed] Error loading TIF: {e}")
        return False

    print("\n>>> STEP 2: Generating STL Surface...")
    try:
        builder = SurfaceBuilder(x, y, z)
        builder.build_mesh()
        builder.export_stl(output_stl_path)

        if builder.mesh is None:
            raise ValueError("Mesh generation failed, builder.mesh is None")

        mesh_bounds = builder.mesh.bounds
        bounds = (
            mesh_bounds[0][0], mesh_bounds[1][0],
            mesh_bounds[0][1], mesh_bounds[1][1],
            mesh_bounds[0][2], mesh_bounds[1][2]
        )
        print(f"  [Success] STL generated at: {output_stl_path}")
        print(f"  Terrain Bounds: X[{bounds[0]:.1f}, {bounds[1]:.1f}], Y[{bounds[2]:.1f}, {bounds[3]:.1f}], Z[{bounds[4]:.1f}, {bounds[5]:.1f}]")
    except Exception as e:
        print(f"  [Failed] Error generating STL: {e}")
        traceback.print_exc()
        return False

    structure_cmds = None
    mesh_import_path = None
    ssi_enabled = getattr(config, 'SSI_ENABLED', False)
    ssi_path = getattr(config, 'SSI_PATH', 'A')
    ssi_strict = getattr(config, 'SSI_STRICT', True)

    if ssi_enabled:
        print("\n>>> STEP 2.5: Structure Processing (SSI)...")
        try:
            from src.schema_parser import StructureSchemaParser

            schema_path = getattr(config, 'SSI_SCHEMA_PATH', None)
            if schema_path is None:
                schema_path = os.path.join(input_dir, 'structure_schema.json')
                if not os.path.exists(schema_path):
                    schema_path_py = os.path.join(input_dir, 'structure_schema.py')
                    if os.path.exists(schema_path_py):
                        schema_path = schema_path_py
                    else:
                        raise FileNotFoundError(
                            f"No structure schema found in {input_dir}. "
                            f"Expected 'structure_schema.json' or 'structure_schema.py', "
                            f"or set SSI_SCHEMA_PATH in config.py"
                        )

            print(f"  Schema file: {schema_path}")

            parser = StructureSchemaParser()
            parser.load(schema_path)
            parser.normalize_units(target_unit='m')
            parser.apply_transform(builder.pca_angle, builder.centroid)
            parser.validate()

            if ssi_path == 'A':
                from src.structure_elements import StructureElementGenerator

                classified = parser.classify_for_path_a()
                n_piles = len(classified.get('piles', []))
                n_cables = len(classified.get('cables', []))
                n_beams = len(classified.get('beams', []))
                n_supported = n_piles + n_cables + n_beams
                unsupported = classified.get('unsupported', [])

                if unsupported:
                    message = f"Path A has unsupported final objects: {unsupported}"
                    if ssi_strict:
                        raise ValueError(message)
                    print(f"  [Path A] {message}")
                if n_supported == 0:
                    raise ValueError(
                        "Path A did not classify any supported structure elements. "
                        "Check schema layer/type fields or switch to Path B."
                    )

                print(
                    f"  [Path A] Generating structure element commands "
                    f"(piles={n_piles}, cables={n_cables}, beams={n_beams})..."
                )

                generator = StructureElementGenerator(config)
                structure_cmds = generator.generate_all(classified)
                commands_path = write_path_a_commands(output_dir, structure_cmds)
                if commands_path:
                    print(f"  [Path A] Commands saved to: {commands_path}")
                print(f"  [Success] {len(structure_cmds)} FLAC3D commands generated.")

            elif ssi_path == 'B':
                from src.gmsh_mesher import GmshMesher

                gmsh_config = {
                    'mesh_size_terrain': getattr(config, 'GMSH_MESH_SIZE_TERRAIN', 2.0),
                    'mesh_size_structure': getattr(config, 'GMSH_MESH_SIZE_STRUCTURE', 0.5),
                    'algorithm': getattr(config, 'GMSH_MESH_ALGORITHM', 6),
                    'optimize': getattr(config, 'GMSH_OPTIMIZE_QUALITY', True),
                }

                primitives, operations = parser.parse()
                final_ids = parser.get_structure_ids()

                print(f"  [Path B] Gmsh solid modeling: {len(primitives)} primitives, {len(operations)} operations")

                mesher = GmshMesher(
                    stl_path=output_stl_path,
                    bounds=bounds,
                    schema_primitives=primitives,
                    schema_operations=operations,
                    layers_config=getattr(config, 'LAYERS', []),
                    gmsh_config=gmsh_config,
                    structure_final_ids=final_ids,
                )

                mesh_import_path = mesher.run(output_dir)
                print(f"  [Success] Gmsh mesh exported to: {mesh_import_path}")

        except Exception as e:
            print(f"  [Error] Structure processing failed: {e}")
            traceback.print_exc()
            if ssi_strict:
                return False
            print("  [Info] Continuing with terrain-only analysis.")

    print("\n>>> STEP 3: FLAC3D Analysis (Console Mode)...")
    runner = Flac3DRunner()
    step3_success = False
    balanced_sav = os.path.join(output_dir, 'model_balanced.sav')
    try:
        if os.path.exists(balanced_sav):
            os.remove(balanced_sav)
            print(f"  [Info] Removed stale balanced model: {balanced_sav}")
        run_fos = not getattr(config, 'RF_ENABLED', False)
        success = runner.run_analysis_sequence(
            output_stl_path, None, bounds, config, run_fos=run_fos,
            structure_cmds=structure_cmds, mesh_import_path=mesh_import_path
        )
        balanced_exists = os.path.exists(balanced_sav)
        print(f"  [Check] model_balanced.sav exists: {balanced_exists}")
        if success or balanced_exists:
            print("  [Success] STEP 3 complete. Balanced model ready.")
            step3_success = True
        else:
            print("  [Warning] FLAC3D process encountered an issue.")
    except Exception as e:
        print(f"  [Error] Unexpected error during FLAC3D invocation: {e}")
        return False

    print(f"\n[Pipeline] step3_success={step3_success}, RF_ENABLED={getattr(config, 'RF_ENABLED', False)}")
    if step3_success and getattr(config, 'RF_ENABLED', False):
        print("\n" + "=" * 55)
        print(">>> STEP 4: Reliability Analysis (Random Field Monte Carlo)")
        print("=" * 55)
        print(f"  ACF Type : {config.RF_ACF}  |  Nsim : {config.RF_NSIM}  |  r_xy : {config.RF_RXY}")
        print()

        confirm = resolve_reliability_choice(runtime_options)
        if confirm is None:
            confirm_text = input("  >>> Start reliability analysis? [Y/n]: ").strip().lower()
            confirm = confirm_text in ('', 'y', 'yes')

        if confirm:
            try:
                runner.run_reliability_sequence(output_dir, config)
            except Exception as e:
                print(f"  [Error] Unexpected error during reliability analysis: {e}")
                return False
        else:
            print("  [Info] Reliability analysis skipped.")
    elif step3_success and not getattr(config, 'RF_ENABLED', False):
        print("\n[Info] RF_ENABLED=False in config.py, skipping reliability analysis.")

    print("\n=== Pipeline Completed ===")
    return step3_success


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
