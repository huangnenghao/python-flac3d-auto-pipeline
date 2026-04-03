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


def validate_path_a_geometry(classified, terrain_vertices, bounds, tolerance=0.5):
    errors = []

    for cable in classified.get('cables', []):
        stats = sample_member_against_terrain(
            cable['start'], cable['end'], terrain_vertices, bounds, tolerance=tolerance
        )
        if stats['embedded_samples'] == 0:
            errors.append(
                f"Cable '{cable['id']}' does not intersect the slope body after transform. "
                f"Check start/end direction in schema."
            )

    return errors
