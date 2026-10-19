#!/usr/bin/env bash
#
# set-gamma.sh: 简易调节半色调 Gamma 曲线
# 用法:
#   set-gamma                  (查看当前状态与说明)
#   set-gamma 0.85             (设置当前默认 stoch_diamond 为 0.85)
#   set-gamma 1.0              (设置当前默认 stoch_diamond 为 1.0)
#   set-gamma 1.08             (恢复色彩完美推荐值 1.08)
#   set-gamma 0.85 all         (同时调整 diamond, grain, 2v2)
#

# Resolve symlinks to locate the real project directory
TARGET="${BASH_SOURCE[0]}"
while [ -h "$TARGET" ]; do
    TARGET_DIR="$(cd -P "$(dirname "$TARGET")" && pwd)"
    TARGET="$(readlink "$TARGET")"
    [[ $TARGET != /* ]] && TARGET="$TARGET_DIR/$TARGET"
done
SCRIPT_DIR="$(cd -P "$(dirname "$TARGET")" && pwd)"

python3 "$SCRIPT_DIR/set_gamma.py" "$@"
