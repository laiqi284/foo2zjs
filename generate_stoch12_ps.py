#!/usr/bin/env python3
"""
Generate crd/zjs/stoch12.ps: Directional 1x2 Micro-Doublet Stochastic Halftone.
Zero-ICM solution: provides full laser saturation per doublet while maintaining
half the visual dot mass of 2x2 clustered screening.
"""

import numpy as np
import scipy.ndimage
import os

def generate_1x2_doublet_ranks(width=128, height=128, seed=42, sigma=1.8):
    n_pairs_x = width // 2
    n_pairs_y = height
    total_pairs = n_pairs_x * n_pairs_y # 8192

    pattern = np.zeros((height, width), dtype=np.float32)
    
    # 10% initial seed
    init_count = int(total_pairs * 0.10)
    rng = np.random.RandomState(seed)
    all_indices = np.arange(total_pairs)
    init_pairs = rng.choice(all_indices, size=init_count, replace=False)
    
    for idx in init_pairs:
        py = idx // n_pairs_x
        px = (idx % n_pairs_x) * 2
        pattern[py, px] = 1.0
        pattern[py, px+1] = 1.0

    # Phase 1: Relaxation (cluster-void swap)
    for _ in range(20):
        energy = scipy.ndimage.gaussian_filter(pattern, sigma=sigma, mode='wrap')
        pair_energy = energy[:, 0::2] + energy[:, 1::2]
        
        active_mask = (pattern[:, 0::2] > 0)
        pair_energy_cluster = np.where(active_mask, pair_energy, -1e9)
        max_idx = np.argmax(pair_energy_cluster)
        cy = max_idx // n_pairs_x
        cx = (max_idx % n_pairs_x) * 2

        pattern[cy, cx] = 0.0
        pattern[cy, cx+1] = 0.0

        energy = scipy.ndimage.gaussian_filter(pattern, sigma=sigma, mode='wrap')
        pair_energy = energy[:, 0::2] + energy[:, 1::2]
        inactive_mask = (pattern[:, 0::2] == 0)
        pair_energy_void = np.where(inactive_mask, pair_energy, 1e9)
        min_idx = np.argmin(pair_energy_void)
        vy = min_idx // n_pairs_x
        vx = (min_idx % n_pairs_x) * 2

        pattern[vy, vx] = 1.0
        pattern[vy, vx+1] = 1.0

    base_pattern = pattern.copy()
    
    # Phase 2: Successively remove doublets
    curr_pattern = base_pattern.copy()
    removal_sequence = []
    for _ in range(init_count):
        energy = scipy.ndimage.gaussian_filter(curr_pattern, sigma=sigma, mode='wrap')
        pair_energy = energy[:, 0::2] + energy[:, 1::2]
        active_mask = (curr_pattern[:, 0::2] > 0)
        pair_energy_cluster = np.where(active_mask, pair_energy, -1e9)
        max_idx = np.argmax(pair_energy_cluster)
        cy = max_idx // n_pairs_x
        cx = (max_idx % n_pairs_x) * 2
        removal_sequence.append((cy, cx))
        curr_pattern[cy, cx] = 0.0
        curr_pattern[cy, cx+1] = 0.0

    # Phase 3: Successively add doublets
    curr_pattern = base_pattern.copy()
    addition_sequence = []
    for _ in range(init_count, total_pairs):
        energy = scipy.ndimage.gaussian_filter(curr_pattern, sigma=sigma, mode='wrap')
        pair_energy = energy[:, 0::2] + energy[:, 1::2]
        inactive_mask = (curr_pattern[:, 0::2] == 0)
        pair_energy_void = np.where(inactive_mask, pair_energy, 1e9)
        min_idx = np.argmin(pair_energy_void)
        vy = min_idx // n_pairs_x
        vx = (min_idx % n_pairs_x) * 2
        addition_sequence.append((vy, vx))
        curr_pattern[vy, vx] = 1.0
        curr_pattern[vy, vx+1] = 1.0

    full_order = list(reversed(removal_sequence)) + addition_sequence
    
    # Map ranks to thresholds with 19838fb's gamma=0.85 optical density boost
    threshold_matrix = np.zeros((height, width), dtype=np.uint8)
    for rank, (py, px) in enumerate(full_order):
        norm = rank / float(total_pairs)
        # Gamma 0.85 tone curve (from trusted commit 19838fb)
        tuned = norm ** 0.85
        thresh = int(np.clip(round(tuned * 254.0 + 1.0), 1, 255))
        threshold_matrix[py, px] = thresh
        threshold_matrix[py, px+1] = thresh

    return threshold_matrix

def matrix_to_hex(mat):
    raw_bytes = mat.tobytes()
    hex_str = raw_bytes.hex().upper()
    lines = [hex_str[i:i+64] for i in range(0, len(hex_str), 64)]
    return "\n".join(lines)

def build_stoch12_ps(output_file):
    print("Generating 1x2 Cyan channel (Seed 101)...")
    cyan_mat = generate_1x2_doublet_ranks(128, 128, seed=101)
    
    print("Generating 1x2 Magenta channel (Seed 202)...")
    magenta_mat = generate_1x2_doublet_ranks(128, 128, seed=202)
    
    print("Generating 1x2 Yellow channel (Dot-on-Dot coupled to Magenta for vivid red/orange)...")
    yellow_mat = magenta_mat.copy()
    
    print("Generating 1x2 Black channel (Seed 303)...")
    black_mat = generate_1x2_doublet_ranks(128, 128, seed=303)

    ps_content = f"""%!PS
%
% 1x2 Directional Micro-Doublet Stochastic Halftone Screen (stoch12.ps)
% Zero-ICM Solution for HP LaserJet Pro CP1025nw
%
% Features:
% - Horizontal 1x2 doublets (42.3um x 84.6um) aligned with laser scan line.
% - Delivers full 2-cycle laser dwell time (140ns), saturating OPC drum potential.
% - Half the area of 2x2 clustered FM: eliminates visual graininess and clumping.
% - Dot-on-Dot coupling between Magenta and Yellow for rich, vibrant warm tones.
% - Built-in gamma=0.85 optical density boost from commit 19838fb.
%
/Stoch12FM <<
  /HalftoneType 5
  /Cyan <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(cyan_mat)}
>
  >>
  /Magenta <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(magenta_mat)}
>
  >>
  /Yellow <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(yellow_mat)}
>
  >>
  /Black <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(black_mat)}
>
  >>
>> def
Stoch12FM /Default Stoch12FM /Black get put
Stoch12FM /Gray Stoch12FM /Black get put
/Default Stoch12FM /Halftone defineresource sethalftone
"""
    with open(output_file, "w") as f:
        f.write(ps_content)
    print(f"Generated {output_file} successfully! (size: {os.path.getsize(output_file)} bytes)")

if __name__ == "__main__":
    out_path = "crd/zjs/stoch12.ps"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    build_stoch12_ps(out_path)
