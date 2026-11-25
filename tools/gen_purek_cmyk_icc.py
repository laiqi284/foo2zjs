#!/usr/bin/env python3
"""Generate standards-compliant 16-bit CMYK ICC profile with Smooth Neutral-Axis Pure-K GCR."""
import argparse
import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import numpy as np

G = 33


def find_default_base_icc():
    candidates = sorted(glob.glob("/usr/share/ghostscript/*/iccprofiles/default_cmyk.icc"), reverse=True)
    candidates.append("/usr/share/color/icc/ghostscript/default_cmyk.icc")
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate 16-bit CMYK ICC profile with Smooth Neutral-Axis Pure-K GCR."
    )
    parser.add_argument(
        "--base-icc",
        default=None,
        help="Path to Ghostscript default_cmyk.icc (auto-discovered if omitted).",
    )
    parser.add_argument(
        "--out",
        default="crd/zjs/cp1025_purek_cmyk.icc",
        help="Output ICC file path. Default: crd/zjs/cp1025_purek_cmyk.icc",
    )
    parser.add_argument(
        "--chroma-flat",
        type=float,
        default=8.5,
        help="Chroma C* radius held at 100%% Pure-K GCR before Gaussian taper. Default: 8.5",
    )
    parser.add_argument(
        "--chroma-sigma",
        type=float,
        default=14.0,
        help="Gaussian taper width sigma (C*) from Pure-K GCR to normal CMYK separation. Default: 14.0",
    )
    args = parser.parse_args()

    if not shutil.which("transicc"):
        sys.exit("Error: 'transicc' not found. Install liblcms2-utils (e.g., sudo apt install liblcms2-utils).")

    base_icc = args.base_icc or find_default_base_icc()
    if not base_icc or not os.path.isfile(base_icc):
        sys.exit("Error: Ghostscript default_cmyk.icc not found. Pass --base-icc PATH explicitly.")

    with open(base_icc, "rb") as f:
        raw = f.read()

    ntags = struct.unpack(">I", raw[128:132])[0]
    tags = {}
    for i in range(ntags):
        sig, off, sz = struct.unpack(">4sII", raw[132 + i * 12 : 144 + i * 12])
        tags[sig.decode("ascii")] = raw[off : off + sz]

    u_grid = np.linspace(0.0, 65535.0, G)
    l_vals = np.clip(u_grid * 100.0 / 65280.0, 0.0, 100.0)
    ab_vals = u_grid / 256.0 - 128.0
    ll, aa, bb = np.meshgrid(l_vals, ab_vals, ab_vals, indexing="ij")
    pts = np.column_stack([ll.ravel(), aa.ravel(), bb.ravel()])

    inp = "\n".join(f"{l:.4f} {a:.4f} {b:.4f}" for l, a, b in pts)
    r = subprocess.run(
        ["transicc", "-i", "*Lab", "-o", base_icc, "-t", "0", "-b"],
        input=inp,
        capture_output=True,
        text=True,
        check=True,
    )
    nums = np.array([float(x) for x in re.findall(r"[CMYK]=([0-9.\-]+)", r.stdout)], dtype=np.float64)
    cmyk0 = (nums.reshape(G, G, G, 4) / 100.0).clip(0.0, 1.0)

    c_n = cmyk0[:, 16, 16, 0]
    m_n = cmyk0[:, 16, 16, 1]
    y_n = cmyk0[:, 16, 16, 2]
    r_m = np.where(c_n > 0.02, m_n / np.maximum(c_n, 1e-6), 0.85)
    r_y = np.where(c_n > 0.02, y_n / np.maximum(c_n, 1e-6), 0.85)
    r_m[-1] = r_m[-2]
    r_y[-1] = r_y[-2]
    k_pure = np.clip((100.0 - l_vals) / 100.0, 0.0, 1.0)

    cmyk_new = cmyk0.copy()
    for li in range(G):
        rm_l, ry_l, cn_l, kp_l = r_m[li], r_y[li], c_n[li], k_pure[li]
        for ai in range(G):
            for bi in range(G):
                chroma = float(np.hypot(ab_vals[ai], ab_vals[bi]))
                if chroma < 0.05:
                    cmyk_new[li, ai, bi] = [0.0, 0.0, 0.0, kp_l]
                    continue
                d_c = max(0.0, chroma - args.chroma_flat)
                alpha = float(np.exp(-((d_c / args.chroma_sigma) ** 2)))
                c0, m0, y0, k0 = cmyk0[li, ai, bi]
                g = min(c0, m0 / max(rm_l, 0.1), y0 / max(ry_l, 0.1))
                g_rem = alpha * g
                c1 = max(0.0, c0 - g_rem)
                m1 = max(0.0, m0 - g_rem * rm_l)
                y1 = max(0.0, y0 - g_rem * ry_l)
                f_rem = min(1.0, g_rem / cn_l) if cn_l > 1e-4 else 0.0
                k1 = min(1.0, k0 + f_rem * max(0.0, kp_l - k0))
                cmyk_new[li, ai, bi] = [c1, m1, y1, k1]

    hdr = struct.pack(">4s4sBBBB", b"mft2", b"\x00\x00\x00\x00", 3, 4, G, 0)
    ident = struct.pack(">9i", 65536, 0, 0, 0, 65536, 0, 0, 0, 65536)
    counts = struct.pack(">HH", 2, 2)
    in_tbl = struct.pack(">6H", 0, 65535, 0, 65535, 0, 65535)
    clut_u16 = np.clip(np.round(cmyk_new * 65535.0), 0, 65535).astype(">u2").tobytes()
    out_tbl = struct.pack(">8H", 0, 65535, 0, 65535, 0, 65535, 0, 65535)
    b2a_tag = hdr + ident + counts + in_tbl + clut_u16 + out_tbl

    desc_str = b"CP1025 Pure-K Neutral GCR CMYK\x00"
    desc_tag = struct.pack(">4s4sI", b"desc", b"\x00\x00\x00\x00", len(desc_str)) + desc_str + b"\x00" * (12 + 67)
    tag_blobs = [
        ("desc", desc_tag),
        ("cprt", tags["cprt"]),
        ("wtpt", tags["wtpt"]),
        ("A2B0", tags["A2B0"]),
        ("B2A0", b2a_tag),
    ]
    all_sigs = ["desc", "cprt", "wtpt", "A2B0", "B2A0", "A2B1", "B2A1", "A2B2", "B2A2"]
    header_len = ((128 + 4 + 12 * len(all_sigs) + 3) // 4) * 4

    offsets, body, cur_off = {}, bytearray(), header_len
    for sig, blob in tag_blobs:
        offsets[sig] = (cur_off, len(blob))
        body.extend(blob)
        pad = (-len(blob)) % 4
        body.extend(b"\x00" * pad)
        cur_off += len(blob) + pad
    for s in ("A2B1", "A2B2"):
        offsets[s] = offsets["A2B0"]
    for s in ("B2A1", "B2A2"):
        offsets[s] = offsets["B2A0"]

    icc_hdr = bytearray(raw[:128])
    struct.pack_into(">I", icc_hdr, 0, header_len + len(body))
    table = bytearray(struct.pack(">I", len(all_sigs)))
    for sig in all_sigs:
        table.extend(struct.pack(">4sII", sig.encode("ascii"), *offsets[sig]))
    while len(icc_hdr) + len(table) < header_len:
        table.append(0)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(icc_hdr)
        f.write(table)
        f.write(body)

    print(f"Base ICC: {base_icc}")
    print(f"Wrote {args.out} ({header_len + len(body)} bytes)")


if __name__ == "__main__":
    main()
