# Auto-generated Monte Carlo Reliability Analysis Script
# Runs inside FLAC3D console via: python execute '<this_file>'
import itasca as it
import numpy as np
import sys
import csv

it.command("python-reset-state false")

# Add project src to path so RandomFieldGenerator can be imported
sys.path.insert(0, r'd:/2026.03 FLAC3D Code-Native/src')
from random_field import RandomFieldGenerator

# ---- Configuration (injected at generation time) ----
NSIM       = 10
ACF_TYPE   = 1
R_XY       = -0.5
FOS_RATIO  = 0.0001
LAYERS_CONFIG = [{'mat_props': {'c_cov': 0.3,
                'cohesion': 10000.0,
                'density': 1800.0,
                'friction': 25.0,
                'phi_cov': 0.2,
                'poisson': 0.35,
                'scale_h': 15.0,
                'scale_v': 1.5,
                'tension': 0.0,
                'young': 50000000.0},
  'name': 'top_soil',
  'thickness': 2.0},
 {'mat_props': {'c_cov': 0.25,
                'cohesion': 50000.0,
                'density': 2200.0,
                'friction': 35.0,
                'phi_cov': 0.15,
                'poisson': 0.25,
                'scale_h': 20.0,
                'scale_v': 2.0,
                'tension': 10000.0,
                'young': 200000000.0},
  'name': 'weathered_rock',
  'thickness': 5.0},
 {'mat_props': {'c_cov': 0.15,
                'cohesion': 200000.0,
                'density': 2500.0,
                'friction': 45.0,
                'phi_cov': 0.1,
                'poisson': 0.2,
                'scale_h': 40.0,
                'scale_v': 5.0,
                'tension': 100000.0,
                'young': 1000000000.0},
  'name': 'bedrock',
  'thickness': None}]
BALANCED_SAV  = r'd:/2026.03 FLAC3D Code-Native/data/test/output/model_balanced.sav'
OUTPUT_CSV    = r'd:/2026.03 FLAC3D Code-Native/data/test/output/fos_results.csv'
# -----------------------------------------------------

print("[RF] Loading balanced model...")
it.command(f"model restore '{BALANCED_SAV}'")

print("[RF] Reading zone data from FLAC3D...")
pos = np.array(it.zonearray.pos())   # shape (N, 3)
n_zones = pos.shape[0]

# Build zone group array
layer_names = [layer['name'] for layer in LAYERS_CONFIG]
zone_groups = np.full(n_zones, 'unknown', dtype=object)
for name in layer_names:
    in_grp = np.array(it.zonearray.in_group(name, 'layers'), dtype=bool)
    zone_groups[in_grp] = name

print(f"[RF] Total zones: {n_zones}")
for name in layer_names:
    count = np.sum(zone_groups == name)
    print(f"  Layer '{name}': {count} zones")

# Generate random field samples
print("[RF] Generating random field samples...")
rf = RandomFieldGenerator(
    layers_config=LAYERS_CONFIG,
    acf_type=ACF_TYPE,
    r_xy=R_XY,
    nsim=NSIM,
    seed=1
)
cohesion_matrix, friction_matrix = rf.generate(pos, zone_groups)
print(f"[RF] Random field generated. Shape: {cohesion_matrix.shape}")

# Monte Carlo FOS loop
print(f"[RF] Starting Monte Carlo simulation (Nsim={NSIM})...")
results = []
for i in range(NSIM):
    # Restore balanced state
    it.command(f"model restore '{BALANCED_SAV}'")
    it.command("zone gridpoint initialize displacement (0,0,0)")
    it.command("zone gridpoint initialize velocity (0,0,0)")

    # Apply random field properties for this simulation
    c_i   = cohesion_matrix[:, i]
    phi_i = np.clip(friction_matrix[:, i], 1.0, 89.0)
    it.zonearray.set_prop_scalar('cohesion', c_i)
    it.zonearray.set_prop_scalar('friction', phi_i)

    # Run FOS (no filename → no intermediate .sav files)
    it.command(f"model factor-of-safety ratio-local {FOS_RATIO}")
    fos = it.fos()

    avg_c   = float(np.mean(c_i)) / 1000.0   # Pa → kPa
    avg_phi = float(np.mean(phi_i))
    results.append([i + 1, round(avg_c, 3), round(avg_phi, 3), round(fos, 6)])

    print(f"  [MC] Sim {i+1:>4d}/{NSIM}: "
          f"avg_c={avg_c:.1f} kPa, avg_phi={avg_phi:.1f} deg, FOS={fos:.4f}")

# Save results to CSV
with open(OUTPUT_CSV, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['sim', 'avg_c_kPa', 'avg_phi_deg', 'FOS'])
    writer.writerows(results)

print(f"[RF] Results saved to: {OUTPUT_CSV}")
