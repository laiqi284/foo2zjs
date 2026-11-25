#!/usr/bin/env python3
"""Generate CP1025 Macro-Stripe Self-Calibration Target (CMYK P7 PAM, layout JSON, and linear LUT)."""
import argparse
import json
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PAPER_SPECS = {
    "a4": {
        "width": 4960,
        "height": 7016,
        "paper_code": 9,
        "fiducials": [(320, 300), (4640, 300), (320, 6500), (4640, 6500)],
    },
    "letter": {
        "width": 5100,
        "height": 6600,
        "paper_code": 1,
        "fiducials": [(320, 300), (4480, 300), (320, 5920), (4480, 5920)],
    },
}

REF_A = [k * 5 for k in range(21)]  # 0..100 step 5
RAW_V = [0, 6, 12, 18, 24, 32, 40, 48, 56, 64, 72, 80, 90, 100, 110, 120, 130, 145, 160, 175, 190, 205, 220, 238, 255]

CHANNELS = [
    ("C", 0, 460),
    ("M", 1, 1810),
    ("Y", 2, 3160),
    ("K", 3, 4510),
]


def load_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def main():
    parser = argparse.ArgumentParser(
        description="Generate CP1025 Macro-Stripe Self-Calibration Target (CMYK P7 PAM + layout JSON + linear LUT)."
    )
    parser.add_argument(
        "--mode",
        choices=("pwm2", "1x1"),
        default="pwm2",
        help="Target halftoning mode: pwm2 (1200x600 2-bit PWM) or 1x1 (600x600 1-bit). Default: pwm2",
    )
    parser.add_argument(
        "--paper",
        choices=("a4", "letter"),
        default="a4",
        help="Paper size: a4 (default) or letter.",
    )
    parser.add_argument(
        "--out-dir",
        default="calib_work",
        help="Output directory for generated PAM, layout JSON, and linear_lut.dat. Default: calib_work",
    )
    args = parser.parse_args()

    spec = PAPER_SPECS[args.paper]
    w, h = spec["width"], spec["height"]
    fiducials = spec["fiducials"]
    clip_x, clip_y = 96, 96  # At 600 dpi base grid

    os.makedirs(args.out_dir, exist_ok=True)
    out_pam = os.path.join(args.out_dir, f"calib_{args.mode}.pam")
    out_json = os.path.join(args.out_dir, f"calib_{args.mode}_layout.json")
    out_lin = os.path.join(args.out_dir, "linear_lut.dat")
    out_zjs = os.path.join(args.out_dir, f"calib_{args.mode}.zjs")

    cmyk = np.zeros((h, w, 4), dtype=np.uint8)

    # 1. Pure-K corner fiducial bullseyes
    for cx, cy in fiducials:
        cmyk[cy - 60 : cy + 60, cx - 60 : cx + 60, 3] = 255
        cmyk[cy - 36 : cy + 36, cx - 36 : cx + 36, 3] = 0
        cmyk[cy - 16 : cy + 16, cx - 16 : cx + 16, 3] = 255

    # 2. Render pure-K text layer (title, channel names, patch labels)
    text_img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(text_img)
    f_title = load_font(44)
    f_sub = load_font(30)
    f_chan = load_font(76)
    f_lbl = load_font(26)

    mode_label = "1200x600 PWM2" if args.mode == "pwm2" else "600x600 1x1"
    title = f"CP1025 {mode_label} ({args.paper.upper()}) Self-Calibration Target (Raw Linear LUT vs 40px Macro-Stripes)"
    sub = "Ref A (top): 0..100% | Raw B (mid): v=0..255 | Ref C (bot): 100..0% (Mirrored)"
    draw.text((460, 255), title, fill=255, font=f_title)
    draw.text((460, 320), sub, fill=255, font=f_sub)

    layout = {
        "mode": args.mode,
        "paper": args.paper,
        "width": w,
        "height": h,
        "clip_x": clip_x,
        "clip_y": clip_y,
        "fiducials": [{"cx": cx, "cy": cy} for cx, cy in fiducials],
        "ref_a_pct": REF_A,
        "raw_v": RAW_V,
        "stripe_period": 40,
        "channels": {},
    }

    x0 = 460
    for ch_name, ch_idx, y_top in CHANNELS:
        draw.text((315, y_top + 590), ch_name, fill=255, font=f_chan)

        ch_info = {
            "channel_index": ch_idx,
            "y_top": y_top,
            "row_a": [],
            "row_b": [],
            "row_c": [],
        }

        # Row A: Forward macro-stripe reference (0..100% in 5% steps)
        ya0, ya1 = y_top + 60, y_top + 420
        period = np.arange(ya1 - ya0) % 40
        for k, a_pct in enumerate(REF_A):
            xa0 = x0 + k * 190
            xa1 = xa0 + 172
            on_rows = (period < 2 * k).astype(np.uint8) * 255
            cmyk[ya0:ya1, xa0:xa1, ch_idx] = on_rows[:, None]
            draw.text((xa0 + 4, y_top + 14), f"{a_pct}", fill=255, font=f_lbl)
            ch_info["row_a"].append({"pct": a_pct, "x0": xa0, "y0": ya0, "x1": xa1, "y1": ya1})

        # Row B: Raw linear-LUT halftone sweep (25 patches)
        yb0, yb1 = y_top + 500, y_top + 860
        for j, v in enumerate(RAW_V):
            xb0 = x0 + j * 160
            xb1 = xb0 + 144
            cmyk[yb0:yb1, xb0:xb1, ch_idx] = v
            draw.text((xb0 + 4, y_top + 454), f"{v}", fill=255, font=f_lbl)
            ch_info["row_b"].append({"v": v, "x0": xb0, "y0": yb0, "x1": xb1, "y1": yb1})

        # Row C: Mirrored/reversed macro-stripe reference (100..0% in 5% steps)
        yc0, yc1 = y_top + 940, y_top + 1220
        period_c = np.arange(yc1 - yc0) % 40
        for k in range(21):
            a_pct = (20 - k) * 5
            xc0 = x0 + k * 190
            xc1 = xc0 + 172
            on_rows = (period_c < 2 * (20 - k)).astype(np.uint8) * 255
            cmyk[yc0:yc1, xc0:xc1, ch_idx] = on_rows[:, None]
            draw.text((xc0 + 4, y_top + 898), f"{a_pct}", fill=255, font=f_lbl)
            ch_info["row_c"].append({"pct": a_pct, "x0": xc0, "y0": yc0, "x1": xc1, "y1": yc1})

        layout["channels"][ch_name] = ch_info

    # Composite pure-K text layer strictly into K channel (binarized so 0 dither error bleeds into K patches)
    k_text = (np.array(text_img, dtype=np.uint8) >= 128).astype(np.uint8) * 255
    cmyk[:, :, 3] = np.maximum(cmyk[:, :, 3], k_text)

    header = f"P7\nWIDTH {w}\nHEIGHT {h}\nDEPTH 4\nMAXVAL 255\nTUPLTYPE CMYK\nENDHDR\n".encode("ascii")
    with open(out_pam, "wb") as f:
        f.write(header)
        f.write(cmyk.tobytes())

    with open(out_json, "w") as f:
        json.dump(layout, f, indent=2)

    with open(out_lin, "w") as f:
        for i in range(256):
            f.write(f"{i} {i} {i} {i}\n")

    print(f"Wrote {out_pam} ({w}x{h} CMYK PAM)")
    print(f"Wrote {out_json}")
    print(f"Wrote {out_lin} (identity 0..255 LUT)")
    print("\nNext steps:")
    pcode = spec["paper_code"]
    if args.mode == "pwm2":
        print(
            f"  ./foo2zjs-dither -p 2 -l {out_lin} -B 1 < {out_pam} | "
            f"./foo2zjs -r1200x600 -p{pcode} -m1 -n1 -d1 -s7 -z3 -c -u 192x96 -l 192x96 -T3 -P > {out_zjs}"
        )
    else:
        print(
            f"  ./foo2zjs-dither -p 1 -l {out_lin} -B 1 < {out_pam} | "
            f"./foo2zjs -r600x600 -p{pcode} -m1 -n1 -d1 -s7 -z3 -c -u 96x96 -l 96x96 -T3 -P > {out_zjs}"
        )
    print(f"  lp -d HP_LaserJet_CP_1025 -o raw {out_zjs}")


if __name__ == "__main__":
    main()
