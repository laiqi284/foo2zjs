#!/usr/bin/env python3
"""
set_gamma.py: Dynamic Gamma / Tone Reproduction Curve (TRC) Tuner for foo2zjs Halftones

Features:
- Instantaneous switching (<10ms) via cached blue-noise void-and-cluster rank arrays.
- Supports:
    1. stoch_diamond: 45° 菱形棋盘 2x2 聚簇挂网 (Diamond 2x2, 厚墨抗马赛克)
    2. stoch2: 经典 2x2 刚性聚簇挂网 (Classic 2x2, 原版高反差)
    3. stoch_grain: 有机胶片无规双点挂网 (Film Grain)
    4. stoch2v2: 渐进式 2x2 聚簇挂网 (Progressive 2x2)
- Automatically updates both crd/zjs/<screen>.ps and /tmp/foo2zjs_<screen>.ps (chmod 666 for CUPS).
- Intelligently defaults to the currently active CUPS halftone screen.
"""

import sys
import os
import json
import subprocess
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CRD_DIR = os.path.join(SCRIPT_DIR, "crd", "zjs")
STATE_FILE = os.path.join(CRD_DIR, ".gamma_state.json")

SCREENS = {
    "diamond": {
        "name": "Diamond Clustered 2x2 (stoch_diamond)",
        "ps_repo": os.path.join(CRD_DIR, "stoch_diamond.ps"),
        "ps_tmp": "/tmp/foo2zjs_stoch_diamond.ps",
        "cache": os.path.join(CRD_DIR, ".ranks_diamond.npz"),
        "dict_name": "DiamondClusteredFM",
        "default_gamma": 1.08,
        "halftone_opt": "stoch_diamond",
    },
    "stoch2": {
        "name": "Classic 2x2 Clustered (stoch2)",
        "ps_repo": os.path.join(CRD_DIR, "stoch2.ps"),
        "ps_tmp": "/tmp/foo2zjs_stoch2.ps",
        "cache": os.path.join(CRD_DIR, ".ranks_stoch2.npz"),
        "dict_name": "GreenNoiseFM",
        "default_gamma": 0.85,
        "halftone_opt": "stoch2",
    },
    "grain": {
        "name": "Organic Film Grain (stoch_grain)",
        "ps_repo": os.path.join(CRD_DIR, "stoch_grain.ps"),
        "ps_tmp": "/tmp/foo2zjs_stoch_grain.ps",
        "cache": os.path.join(CRD_DIR, ".ranks_grain.npz"),
        "dict_name": "OrganicGrainFM",
        "default_gamma": 1.08,
        "halftone_opt": "stoch_grain",
    },
    "2v2": {
        "name": "Progressive 2x2 Clustered (stoch2v2)",
        "ps_repo": os.path.join(CRD_DIR, "stoch2v2.ps"),
        "ps_tmp": "/tmp/foo2zjs_stoch2v2.ps",
        "cache": os.path.join(CRD_DIR, ".ranks_stoch2v2.npz"),
        "dict_name": "GreenNoiseFMv2",
        "default_gamma": 1.08,
        "halftone_opt": "stoch2v2",
    },
}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"diamond": 1.08, "stoch2": 0.85, "grain": 1.08, "2v2": 1.08}

def save_state(state):
    os.makedirs(CRD_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def matrix_to_hex(mat):
    raw_bytes = mat.tobytes()
    hex_str = raw_bytes.hex().upper()
    lines = [hex_str[i:i+64] for i in range(0, len(hex_str), 64)]
    return "\n".join(lines)

def build_ps_content(dict_name, title, gamma, c_mat, m_mat, y_mat, k_mat):
    return f"""%!PS
%
% {title}
% Configured Gamma: {gamma:.2f}
%
/{dict_name} <<
  /HalftoneType 5
  /Cyan <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(c_mat)}
>
  >>
  /Magenta <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(m_mat)}
>
  >>
  /Yellow <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(y_mat)}
>
  >>
  /Black <<
    /HalftoneType 3
    /Width 128
    /Height 128
    /Thresholds <
{matrix_to_hex(k_mat)}
>
  >>
>> def
{dict_name} /Default {dict_name} /Black get put
{dict_name} /Gray {dict_name} /Black get put
/Default {dict_name} /Halftone defineresource sethalftone
"""

def apply_gamma_diamond(gamma):
    cfg = SCREENS["diamond"]
    data = np.load(cfg["cache"])
    c_order = data["c"]
    m_order = data["m"]
    y_order = data["y"]
    k_order = data["k"]
    n_blocks = 4096.0

    def to_thresh(order_grid):
        norm = order_grid / n_blocks
        norm_trc = norm ** gamma
        thresh = np.clip(np.round(norm_trc * 254.0 + 1.0), 1, 255).astype(np.uint8)
        return np.repeat(np.repeat(thresh, 2, axis=0), 2, axis=1)

    c_mat = to_thresh(c_order)
    m_mat = to_thresh(m_order)
    y_mat = to_thresh(y_order)
    k_mat = to_thresh(k_order)

    ps_text = build_ps_content(
        cfg["dict_name"],
        "45-Degree Diamond Clustered FM Screening (stoch_diamond.ps)",
        gamma, c_mat, m_mat, y_mat, k_mat
    )
    deploy_ps(cfg, ps_text)

def apply_gamma_stoch2(gamma):
    cfg = SCREENS["stoch2"]
    data = np.load(cfg["cache"])
    c_rank = data["c"]
    m_rank = data["m"]
    y_rank = data["y"]
    k_rank = data["k"]
    size = 64

    def to_thresh(rank):
        base_th = (rank * 254.0 / (size * size - 1)).astype(np.uint8)
        arr = base_th.astype(float) / 254.0
        tuned = (np.power(arr, gamma) * 254.0).clip(0, 254).astype(np.uint8)
        return np.repeat(np.repeat(tuned, 2, axis=0), 2, axis=1)

    c_mat = to_thresh(c_rank)
    m_mat = to_thresh(m_rank)
    y_mat = to_thresh(y_rank)
    k_mat = to_thresh(k_rank)

    ps_text = build_ps_content(
        cfg["dict_name"],
        f"2x2 Cluster-Dot Green Noise FM Screening (stoch2.ps)\n% Density calibrated: gamma = {gamma:.2f}",
        gamma, c_mat, m_mat, y_mat, k_mat
    )
    deploy_ps(cfg, ps_text)

def apply_gamma_grain(gamma):
    cfg = SCREENS["grain"]
    data = np.load(cfg["cache"])
    c_ranks = data["c"]
    m_ranks = data["m"]
    y_ranks = data["y"]
    k_ranks = data["k"]
    y_coords = data["y_coords"]
    x0_coords = data["x0_coords"]
    x1_coords = data["x1_coords"]
    total_doublets = 8192.0

    def to_thresh(ranks):
        mat = np.zeros((128, 128), dtype=np.uint8)
        norm = ranks / total_doublets
        norm_trc = norm ** gamma
        thresh = np.clip(np.round(norm_trc * 254.0 + 1.0), 1, 255).astype(np.uint8)
        mat[y_coords, x0_coords] = thresh
        mat[y_coords, x1_coords] = thresh
        return mat

    c_mat = to_thresh(c_ranks)
    m_mat = to_thresh(m_ranks)
    y_mat = to_thresh(y_ranks)
    k_mat = to_thresh(k_ranks)

    ps_text = build_ps_content(
        cfg["dict_name"],
        "Organic Seamless Stochastic FM Screening (stoch_grain.ps)",
        gamma, c_mat, m_mat, y_mat, k_mat
    )
    deploy_ps(cfg, ps_text)

def apply_gamma_2v2(gamma):
    cfg = SCREENS["2v2"]
    data = np.load(cfg["cache"])
    c_order = data["c"]
    m_order = data["m"]
    y_order = data["y"]
    k_order = data["k"]
    n_clusters = 4096.0
    delay_ranks = int(4096 * 0.10)

    def to_thresh(order_grid):
        matrix = np.zeros((128, 128), dtype=np.uint8)
        for cy in range(64):
            for cx in range(64):
                r = order_grid[cy, cx]
                norm_a = r / n_clusters
                r_b = min(4095, r + delay_ranks)
                norm_b = r_b / n_clusters
                thresh_a = int(np.clip(round((norm_a ** gamma) * 254.0 + 1.0), 1, 255))
                thresh_b = int(np.clip(round((norm_b ** gamma) * 254.0 + 1.0), 1, 255))
                py = cy * 2
                px = cx * 2
                matrix[py, px] = thresh_a
                matrix[py, px+1] = thresh_a
                matrix[py+1, px] = thresh_b
                matrix[py+1, px+1] = thresh_b
        return matrix

    c_mat = to_thresh(c_order)
    m_mat = to_thresh(m_order)
    y_mat = to_thresh(y_order)
    k_mat = to_thresh(k_order)

    ps_text = build_ps_content(
        cfg["dict_name"],
        "Progressive 2x2 Clustered FM Screening v2 (stoch2v2.ps)",
        gamma, c_mat, m_mat, y_mat, k_mat
    )
    deploy_ps(cfg, ps_text)

def deploy_ps(cfg, ps_text):
    # 1. Write to repository crd/zjs
    with open(cfg["ps_repo"], "w") as f:
        f.write(ps_text)
    # 2. Write to persistent /var/tmp/foo2zjs/crd/
    var_crd = os.path.join("/var/tmp/foo2zjs/crd", os.path.basename(cfg["ps_repo"]))
    try:
        os.makedirs("/var/tmp/foo2zjs/crd", exist_ok=True)
        with open(var_crd, "w") as f:
            f.write(ps_text)
        os.chmod(var_crd, 0o666)
    except Exception:
        pass
    # 3. Write to /tmp for backward compatibility
    try:
        with open(cfg["ps_tmp"], "w") as f:
            f.write(ps_text)
        os.chmod(cfg["ps_tmp"], 0o666)
    except Exception:
        pass

def ensure_persistent_runtime():
    try:
        os.makedirs("/var/tmp/foo2zjs/crd", exist_ok=True)
        os.chmod("/var/tmp/foo2zjs", 0o777)
        wrap_src = os.path.join(SCRIPT_DIR, "foo2zjs-wrapper")
        wrap_dst = "/var/tmp/foo2zjs/foo2zjs-wrapper"
        pst_src = os.path.join(SCRIPT_DIR, "foo2zjs-pstops")
        pst_dst = "/var/tmp/foo2zjs/foo2zjs-pstops"
        if os.path.exists(wrap_src):
            import shutil
            shutil.copyfile(wrap_src, wrap_dst)
            os.chmod(wrap_dst, 0o777)
        if os.path.exists(pst_src):
            import shutil
            shutil.copyfile(pst_src, pst_dst)
            os.chmod(pst_dst, 0o777)
    except Exception:
        pass

def get_cups_active_halftone():
    try:
        res = subprocess.run(["lpoptions", "-p", "HP_LaserJet_CP_1025", "-l"],
                             capture_output=True, text=True, check=False)
        for line in res.stdout.splitlines():
            if line.startswith("halftone/"):
                for item in line.split():
                    if item.startswith("*"):
                        return item[1:]
    except Exception:
        pass
    return "stoch_diamond"

def show_status():
    state = load_state()
    active_ht = get_cups_active_halftone()
    print("=" * 68)
    print("     HP LaserJet CP1025 半色调 Gamma / 色调曲线极速调节工具")
    print("=" * 68)
    print(f"当前 CUPS 默认挂网: \033[1;32m{active_ht}\033[0m")
    print("-" * 68)
    print("各半色调方案当前 Gamma 值:")
    for key, cfg in SCREENS.items():
        g = state.get(key, cfg["default_gamma"])
        is_active = (active_ht == cfg["halftone_opt"])
        tag = " \033[1;32m[当前默认]\033[0m" if is_active else ""
        print(f"  • {key:7s} ({cfg['name']}): \033[1;33mGamma = {g:.2f}\033[0m{tag}")
    print("-" * 68)
    print("Gamma 效果速查:")
    print("  • Gamma = 0.85 : 压深加浓、黑位极深、高反差浮雕质感（经典 2x2 原装标定）")
    print("  • Gamma = 1.00 : 数学线性直出、无反网点扩大补偿")
    print("  • Gamma = 1.08 : 反网点扩大补偿、中调通透真实、高反光 3D 色彩（实测推荐）")
    print("-" * 68)
    print("使用方法:")
    print("  set-gamma <gamma> [目标方案: diamond | stoch2 | grain | 2v2 | all]")
    print("")
    print("示例:")
    print("  set-gamma 0.85            # 直接调节当前默认挂网为 Gamma 0.85")
    print("  set-gamma 1.0 stoch2      # 将经典 2x2 (stoch2) 设为 Gamma 1.0")
    print("  set-gamma 0.85 stoch2     # 将经典 2x2 (stoch2) 恢复默认 0.85")
    print("  set-gamma 1.08 diamond    # 将 45° 菱形 2x2 设为推荐的 Gamma 1.08")
    print("  set-gamma 0.85 all        # 同时将全部方案统一设为 Gamma 0.85")
    print("=" * 68)

def main():
    ensure_persistent_runtime()
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help", "status"):
        show_status()
        return

    try:
        gamma = float(sys.argv[1])
        if gamma <= 0.1 or gamma >= 5.0:
            print(f"错误: Gamma 值 {gamma} 超出合理范围 (建议 0.5 ~ 2.0)")
            sys.exit(1)
    except ValueError:
        print(f"错误: 无法解析 Gamma 参数 '{sys.argv[1]}'")
        print("用法示例: set-gamma 0.85")
        sys.exit(1)

    target = None
    if len(sys.argv) >= 3:
        raw_target = sys.argv[2].lower()
        if raw_target in ("stoch_diamond", "diamond", "dia"):
            target = "diamond"
        elif raw_target in ("stoch2", "2x2", "classic", "legacy", "old2x2"):
            target = "stoch2"
        elif raw_target in ("stoch_grain", "grain", "film", "organic"):
            target = "grain"
        elif raw_target in ("stoch2v2", "stoch2_v2", "v2", "2v2", "2x2v2"):
            target = "2v2"
        elif raw_target == "all":
            target = "all"
        else:
            print(f"错误: 未知目标方案 '{raw_target}'，可选: diamond, stoch2, grain, 2v2, all")
            sys.exit(1)
    else:
        # Intelligently default to active CUPS halftone
        active_ht = get_cups_active_halftone()
        if active_ht in ("stoch2", "2x2"):
            target = "stoch2"
        elif active_ht == "stoch_grain":
            target = "grain"
        elif active_ht == "stoch2v2":
            target = "2v2"
        else:
            target = "diamond"

    state = load_state()

    targets_to_update = []
    if target == "all":
        targets_to_update = ["diamond", "stoch2", "grain", "2v2"]
    elif target in SCREENS:
        targets_to_update = [target]

    print(f"\n>> 正在应用 Gamma = \033[1;32m{gamma:.2f}\033[0m ...")
    for t in targets_to_update:
        if t == "diamond":
            apply_gamma_diamond(gamma)
        elif t == "stoch2":
            apply_gamma_stoch2(gamma)
        elif t == "grain":
            apply_gamma_grain(gamma)
        elif t == "2v2":
            apply_gamma_2v2(gamma)
        state[t] = gamma
        print(f"  ✓ 已更新 {SCREENS[t]['name']} (Gamma = {gamma:.2f})")

    save_state(state)
    print("\n\033[1;32m配置已实时生效！\033[0m")
    if gamma < 1.0:
        print("  [效果特性] 画面加深加浓，暗部黑位更厚重，高反差浮雕质感。")
    elif abs(gamma - 1.0) < 1e-4:
        print("  [效果特性] 数学线性直出，无反网点扩大补偿。")
    else:
        print("  [效果特性] 反网点扩大曲线，高光与肤色通透纯正，消除热辊膨胀过深。")

    print("\n可以直接运行以下命令测试打印:")
    print("  lp /path/to/your/document.pdf\n")

if __name__ == "__main__":
    main()
