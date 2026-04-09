SUPPORTED_PATH_B_PRIMITIVES = {"box", "cylinder", "polyline_extrude"}
UNSUPPORTED_PATH_B_LINEAR = {"line_segment", "member"}
SUPPORTED_PATH_B_OPERATIONS = {
    "boolean_union",
    "boolean_difference",
    "boolean_intersection",
}


def validate_path_b_schema(primitives, operations, final_ids):
    """
    Validate whether schema objects can be safely consumed by Path B.

    Path B currently supports only solidifiable structures that can be turned
    into 3D OCC solids in Gmsh. 1D members such as beam/cable line definitions
    must be rejected explicitly to avoid silent geometry loss.
    """
    errors = []
    warnings = []

    status_map = {}
    primitive_types = {}

    for prim in primitives:
        prim_id = prim.get("id")
        prim_type = prim.get("type")
        primitive_types[prim_id] = prim_type

        if prim_type in SUPPORTED_PATH_B_PRIMITIVES:
            status_map[prim_id] = ("solid", f"primitive '{prim_id}'")
        elif prim_type in UNSUPPORTED_PATH_B_LINEAR:
            status_map[prim_id] = (
                "linear",
                f"primitive '{prim_id}' ({prim_type}) is a 1D member",
            )
        else:
            status_map[prim_id] = (
                "unsupported",
                f"primitive '{prim_id}' has unsupported type '{prim_type}'",
            )

    for op in operations:
        op_type = op.get("op")
        result_id = op.get("result") or op.get("id")

        if op_type not in SUPPORTED_PATH_B_OPERATIONS:
            status_map[result_id] = (
                "unsupported",
                f"operation '{result_id}' uses unsupported op '{op_type}'",
            )
            continue

        if op_type in ("boolean_union", "boolean_intersection"):
            ref_ids = list(op.get("inputs", []))
        else:
            ref_ids = [op.get("target")] + list(op.get("tools", []))

        ref_ids = [rid for rid in ref_ids if rid]
        missing = [rid for rid in ref_ids if rid not in status_map]
        if missing:
            status_map[result_id] = (
                "unsupported",
                f"operation '{result_id}' references missing ids {missing}",
            )
            continue

        non_solid = [rid for rid in ref_ids if status_map[rid][0] != "solid"]
        if non_solid:
            reasons = ", ".join(status_map[rid][1] for rid in non_solid)
            status_map[result_id] = (
                "unsupported",
                f"operation '{result_id}' depends on non-solid inputs: {reasons}",
            )
            continue

        status_map[result_id] = ("solid", f"operation '{result_id}'")

    if final_ids:
        for final_id in final_ids:
            if final_id not in status_map:
                errors.append(
                    f"Path B final object '{final_id}' is not defined by primitives/operations."
                )
                continue

            status, reason = status_map[final_id]
            if status == "solid":
                continue
            if status == "linear":
                errors.append(
                    f"Path B does not support 1D beam/cable members. "
                    f"Final object '{final_id}' must be modeled with solidifiable primitives or use Path A."
                )
            else:
                errors.append(f"Path B cannot realize final object '{final_id}': {reason}.")
    else:
        unsupported_prims = [
            pid for pid, (status, _) in status_map.items()
            if pid in primitive_types and status != "solid"
        ]
        if unsupported_prims:
            errors.append(
                "Path B without outputs.final_objects would silently ignore unsupported primitives: "
                + ", ".join(unsupported_prims)
                + ". Define solid final_objects explicitly or switch to Path A."
            )

    return errors, warnings
