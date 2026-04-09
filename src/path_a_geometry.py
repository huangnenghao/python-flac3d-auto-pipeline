import numpy as np


def _estimate_surface_z(vertices_xy, vertices_z, x, y, neighbors=12):
    dx = vertices_xy[:, 0] - x
    dy = vertices_xy[:, 1] - y
    dist2 = dx * dx + dy * dy

    exact = np.where(dist2 < 1e-12)[0]
    if exact.size:
        return float(np.max(vertices_z[exact]))

    count = min(max(1, neighbors), len(vertices_z))
    idx = np.argpartition(dist2, count - 1)[:count]
    weights = 1.0 / np.maximum(dist2[idx], 1e-12)
    return float(np.sum(weights * vertices_z[idx]) / np.sum(weights))


def sample_member_against_terrain(start, end, terrain_vertices, bounds, samples=11, tolerance=0.5):
    vertices_xy = terrain_vertices[:, :2]
    vertices_z = terrain_vertices[:, 2]
    xmin, xmax, ymin, ymax, _, _ = bounds

    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)

    embedded = 0
    above_surface = 0
    outside_xy = 0

    for t in np.linspace(0.0, 1.0, samples):
        point = start + t * (end - start)
        x, y, z = point.tolist()
        if x < xmin or x > xmax or y < ymin or y > ymax:
            outside_xy += 1
            continue

        surface_z = _estimate_surface_z(vertices_xy, vertices_z, x, y)
        if z <= surface_z + tolerance:
            embedded += 1
        else:
            above_surface += 1

    return {
        'embedded_samples': embedded,
        'above_surface_samples': above_surface,
        'outside_xy_samples': outside_xy,
        'samples': samples,
    }


def _point_in_xy_bounds(point, bounds, tolerance=0.5):
    xmin, xmax, ymin, ymax, _, _ = bounds
    x, y = float(point[0]), float(point[1])
    return (xmin - tolerance) <= x <= (xmax + tolerance) and (ymin - tolerance) <= y <= (ymax + tolerance)


def _point_in_z_bounds(point, bounds, lower_tolerance=20.0, upper_tolerance=2.0):
    _, _, _, _, zmin, zmax = bounds
    z = float(point[2])
    return (zmin - lower_tolerance) <= z <= (zmax + upper_tolerance)


def _pile_top_point(pile):
    return [pile.get('top_x', pile['center_x']), pile.get('top_y', pile['center_y']), pile['z_top']]


def _pile_bottom_point(pile):
    return [pile['center_x'], pile['center_y'], pile['z_bottom']]


def _distance(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return float(np.linalg.norm(a - b))


def validate_path_a_geometry(classified, terrain_vertices, bounds, tolerance=0.5):
    errors = []
    pile_head_points = []

    for pile in classified.get('piles', []):
        top_point = _pile_top_point(pile)
        bottom_point = _pile_bottom_point(pile)

        if abs(float(top_point[0]) - float(bottom_point[0])) > tolerance or abs(float(top_point[1]) - float(bottom_point[1])) > tolerance:
            errors.append(
                f"Pile '{pile['id']}' is not vertical in XY after transform. "
                f"Path A currently supports vertical piles only."
            )

        for point_name, point in (('top', top_point), ('bottom', bottom_point)):
            if not _point_in_xy_bounds(point, bounds):
                errors.append(f"Pile '{pile['id']}' {point_name} lies outside terrain XY bounds.")
            if not _point_in_z_bounds(point, bounds):
                errors.append(f"Pile '{pile['id']}' {point_name} lies outside terrain Z bounds.")

        surface_z = _estimate_surface_z(terrain_vertices[:, :2], terrain_vertices[:, 2], top_point[0], top_point[1])
        if top_point[2] > surface_z + 5.0:
            errors.append(
                f"Pile '{pile['id']}' top is too far above terrain surface "
                f"({top_point[2]:.2f} vs surface {surface_z:.2f})."
            )

        bottom_surface_z = _estimate_surface_z(terrain_vertices[:, :2], terrain_vertices[:, 2], bottom_point[0], bottom_point[1])
        if bottom_point[2] > bottom_surface_z - 0.5:
            errors.append(
                f"Pile '{pile['id']}' bottom is not sufficiently embedded below terrain surface."
            )

        pile_head_points.append(top_point)

    for cable in classified.get('cables', []):
        start = cable['start']
        end = cable['end']
        for point_name, point in (('start', start), ('end', end)):
            if not _point_in_xy_bounds(point, bounds):
                errors.append(f"Cable '{cable['id']}' {point_name} lies outside terrain XY bounds.")
            if not _point_in_z_bounds(point, bounds):
                errors.append(f"Cable '{cable['id']}' {point_name} lies outside terrain Z bounds.")

        stats = sample_member_against_terrain(
            start, end, terrain_vertices, bounds, tolerance=tolerance
        )
        if stats['embedded_samples'] == 0:
            errors.append(
                f"Cable '{cable['id']}' does not intersect the slope body after transform. "
                f"Check start/end direction in schema."
            )
            continue

        if stats['embedded_samples'] < max(2, stats['samples'] // 4):
            errors.append(
                f"Cable '{cable['id']}' is only weakly embedded in the slope body. "
                f"Increase the anchored portion inside the terrain."
            )

        if stats['outside_xy_samples'] > stats['samples'] // 2:
            errors.append(
                f"Cable '{cable['id']}' is mostly outside terrain XY bounds after transform."
            )

        start_surface_z = _estimate_surface_z(terrain_vertices[:, :2], terrain_vertices[:, 2], start[0], start[1])
        end_surface_z = _estimate_surface_z(terrain_vertices[:, :2], terrain_vertices[:, 2], end[0], end[1])
        start_near_surface = start[2] >= start_surface_z - 2.0 * tolerance
        end_near_surface = end[2] >= end_surface_z - 2.0 * tolerance
        start_deep = start[2] <= start_surface_z - 2.0 * tolerance
        end_deep = end[2] <= end_surface_z - 2.0 * tolerance
        if not ((start_near_surface and end_deep) or (end_near_surface and start_deep)):
            errors.append(
                f"Cable '{cable['id']}' should have one end near/external to the surface and the other anchored inside."
            )

    if pile_head_points:
        beam_connection_tol = 3.0
        for beam in classified.get('beams', []):
            for point_name, point in (('start', beam['start']), ('end', beam['end'])):
                if not _point_in_xy_bounds(point, bounds):
                    errors.append(f"Beam '{beam['id']}' {point_name} lies outside terrain XY bounds.")
                if not _point_in_z_bounds(point, bounds):
                    errors.append(f"Beam '{beam['id']}' {point_name} lies outside terrain Z bounds.")

                nearest_pile = min((_distance(point, pile_head) for pile_head in pile_head_points), default=np.inf)
                if nearest_pile > beam_connection_tol:
                    errors.append(
                        f"Beam '{beam['id']}' {point_name} is not close to any pile head "
                        f"(nearest distance {nearest_pile:.2f} m)."
                    )

            if 'direction_y' in beam:
                errors.append(
                    f"Beam '{beam['id']}' provides direction_y, but Path A beam local-axis transfer is not implemented."
                )

    return errors
