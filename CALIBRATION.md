# HP LaserJet Pro CP1025 / CP1025nw 自校准指南（无分光光度计方案）

本仓库在 [`tools/`](tools/) 目录内置了一套无需分光光度计、仅凭普通手机拍照即可完成 C/M/Y/K 四通道阶调线性化的自校准工具链，同时包含中性轴纯 K CMYK ICC 生成脚本。

当更换不同品牌碳粉（如第三方兼容粉鼓）、更换纸张类型，或发现高光/中间调阶调偏移时，可按本指南重新标定驱动 LUT。

---

## 1. 原理简介

1. **同页 40 px 宏观条纹参考尺（Macro-Stripe Self-Calibration）**：
   - 将 C、M、Y、K 四个通道各打印三行：
     - **Row A（顶部参考尺）**：`0% .. 100%`（步进 `5%`）的 **40 扫描行（1.69 mm）周期纯 `00`/`11` 宏观条纹**。因其边缘密度仅为 `1x1` 散点网点的 1/20，受激光轮廓扩散与碳粉网点扩大（dot gain）的干扰极小，反射率近似满足 Murray-Davies 线性关系。
     - **Row B（待测原始曲线）**：绕过已校准 LUT、使用线性 `0..255` 恒等 LUT 打印的 **25 档原始误差扩散色块**（`v = 0..255`）。
     - **Row C（底部反序参考尺）**：`100% .. 0%` 镜像参考尺，用于校验左右光照方向。
   - 由于 Row A 与 Row B 印在同一张纸上并经过同一台手机的同一次成像，求解过程先按四角回字形定位标做单应性（Homography）透视矫正，再对块间白纸间隙做局部平场归一化，最后用 Row A 的反射率曲线直接非参数反演 Row B，**天然抵消手机相机的 HDR、伽马编码、自动曝光与照度不均**。
2. **CIE $L^*$ 感知均匀目标曲线**：
   - 求解器将反演得到的物理覆盖率曲线 $a_{\mathrm{eff}}(v)$ 映射到人眼感知线性阶调 CIE $L^*$（默认实地碳粉反射率参数 `--rs 0.14`，等价约 ISO TVI +15%）。
   - 若觉得中间调偏深或偏浅，可微调 `--rs`（数值越小中间调越亮，范围建议 `0.10 .. 0.20`）。
3. **中性轴纯 K ICC（`cp1025_purek_cmyk.icc`）**：
   - 在 `33×33×33` CMYK 输出 LUT 中将 CIE $a^*=b^*=0$ 中性灰强制映射为 `0, 0, 0, K`（纯 K 碳粉），并通过光滑高斯衰减窗在离开中性轴后平滑过渡回标准 CMYK 彩色分色；原生 CMYK 文档则直通不经过此转换。

---

## 2. 环境依赖

```bash
sudo apt install build-essential python3-numpy python3-scipy python3-pillow liblcms2-utils
```

> 说明：`liblcms2-utils` 提供 `transicc` 命令，仅在步骤 5 重新生成 ICC 文件时需要；普通 LUT 校色只需前三个 Python 库。

---

## 3. 步骤 1：编译驱动并生成标定靶（默认 A4 / `1200x600` PWM2）

在仓库根目录执行：

```bash
make
python3 tools/gen_calib_target.py --mode pwm2 --paper a4 --out-dir calib_work
```

将在 `calib_work/` 下生成：
- `calib_work/calib_pwm2.pam`：CMYK `P7` PAM 标定图像（`4960×7016`，对应 A4 @ 600 dpi）。
- `calib_work/calib_pwm2_layout.json`：定位标与色块坐标元数据（供步骤 4 读取）。
- `calib_work/linear_lut.dat`：256 行线性恒等表（`0 0 0 0` 到 `255 255 255 255`）。

> [!IMPORTANT]
> **`foo2zjs-dither -l none` 会回退到固件内置已校准 LUT，而非线性输出！**
> 测量打印机原始硬件响应时，**必须**使用脚本生成的 `-l calib_work/linear_lut.dat`。

若使用 `Letter` 纸或同时需要校准 `600x600` (`1x1`) 模式，可切换 `--paper letter` 或 `--mode 1x1`。

---

## 4. 步骤 2：编码 `.zjs` 并原始打印

### `1200x600` PWM2 模式（默认 A4 `-p9`；若为 Letter 改为 `-p1`）：

```bash
./foo2zjs-dither -p 2 -l calib_work/linear_lut.dat -B 1 < calib_work/calib_pwm2.pam | \
  ./foo2zjs -r1200x600 -p9 -m1 -n1 -d1 -s7 -z3 -c -u 192x96 -l 192x96 -T3 -P > calib_work/calib_pwm2.zjs
```

### 若需同时校准 `600x600` `1x1` 模式：

```bash
python3 tools/gen_calib_target.py --mode 1x1 --paper a4 --out-dir calib_work
./foo2zjs-dither -p 1 -l calib_work/linear_lut.dat -B 1 < calib_work/calib_1x1.pam | \
  ./foo2zjs -r600x600 -p9 -m1 -n1 -d1 -s7 -z3 -c -u 96x96 -l 96x96 -T3 -P > calib_work/calib_1x1.zjs
```

### 可选流校验（确认纸张码与 4 平面完整）：

```bash
./zjsdecode -h < calib_work/calib_pwm2.zjs | head -n 30
# 应看到 ZJI_DMPAPER = 9 (A4)、4 个颜色平面 (ZJI_NBIE = 4) 及对应分辨率
```

### 发送到打印机（Raw 模式直通，不经过 CUPS 二次过滤）：

```bash
# 本机直接连接或已配置同网段 CUPS 队列时：
lp -d HP_LaserJet_CP_1025 -o raw calib_work/calib_pwm2.zjs

# 若打印服务器在远程主机（例如 ssh 传输后执行）：
scp calib_work/calib_pwm2.zjs user@print-server:/tmp/
ssh user@print-server "lp -d HP_LaserJet_CP_1025 -o raw /tmp/calib_pwm2.zjs"
```

---

## 5. 步骤 3：手机拍摄标定页

为保证反演精度，拍照时请遵守以下条件：
1. **垫白纸放平**：避免透光底纹或边缘翘曲。
2. **均匀散射光**：推荐室内散射光或窗边漫射光；避开顶灯在纸面碳粉上的镜面高光反光。
3. **垂直正对、框全四角**：确保页面四个角的回字形定位标（Bullseye）全部完整留在画面内，且纸张尽量占满画面大部分面积。
4. **使用原始照片**：不要使用相机“文档扫描/黑白增强/HDR 锐化滤镜”，不要手动裁剪或二次压缩截图（脚本会自动处理手机 EXIF 旋转）。

---

## 6. 步骤 4：照片反演解算 CIE $L^*$ LUT

将手机原图传回电脑后运行（默认输出覆盖 `crd/zjs/lut_cmyk_pwm2.dat` 与 `embedded_lut_pwm2.h`）：

```bash
python3 tools/solve_lut_from_photo.py \
  --photo /path/to/calib_photo.jpg \
  --layout calib_work/calib_pwm2_layout.json
```

运行后重点检查输出：
- `Homography max reprojection error: 0.00xx px`：必须显著小于 `1.0 px`，说明四角定位与透视矫正完全准确。
- 16 档覆盖率预测表（`C/M/Y/K: v->a%`）：确认各档位单调递增、高光（5%）非 0 且暗调平滑达到 100%。

若需调整整体中间调深浅，可指定 `--rs`（默认 `0.14`）；若要校准 `600x600` (`1x1`) 模式，传入对应的 `--layout calib_work/calib_1x1_layout.json`（会默认输出到 `crd/zjs/lut_cmyk_1x1.dat` 和 `embedded_lut.h`）：

```bash
python3 tools/solve_lut_from_photo.py \
  --photo /path/to/calib_1x1_photo.jpg \
  --layout calib_work/calib_1x1_layout.json \
  --mode 1x1
```

---

## 7. 步骤 5（可选）：重新生成中性轴纯 K sRGB ICC

默认情况下无需重新生成 `crd/zjs/cp1025_purek_cmyk.icc`。如需调整纯 K 锁定的彩度半径（默认 `--chroma-flat 8.5`）或边缘过渡宽度（默认 `--chroma-sigma 14.0`），可执行：

```bash
python3 tools/gen_purek_cmyk_icc.py
```

脚本会自动查找系统中的 `/usr/share/ghostscript/*/iccprofiles/default_cmyk.icc` 并生成新的 `crd/zjs/cp1025_purek_cmyk.icc`。

---

## 8. 步骤 6：重新编译、打包 `.deb` 并部署验证

新的 LUT 已同时写入 `crd/zjs/lut_cmyk_*.dat`（运行时读取）和 `embedded_lut*.h`（编译期内置回退），执行完整重编与打包：

```bash
make clean && make && make deb
```

打包完成后会生成 `../printer-driver-foo2zjs-cp1025_<VERSION>_<ARCH>.deb`，安装到本机或打印服务器：

```bash
sudo apt install ../printer-driver-foo2zjs-cp1025_*.deb
```

清理临时标定文件：

```bash
rm -rf calib_work
```

验证建议：
1. 从浏览器或 GTK 文档查看器打印一张包含 5% 浅灰、渐变与彩图的测试页，确认 sRGB 浅灰仅消耗纯 K 碳粉且阶调连续无断层。
2. 如需确认输出流中无非法 `01` 脉冲码，可截取打印作业头尾通过 `./zjsdecode -h` 抽检。
