# HP LaserJet Pro CP1025 / CP1025nw Dedicated `foo2zjs` Driver

Specialized, lightweight `foo2zjs` driver build tailored exclusively for **HP LaserJet Pro CP1025 / CP1025nw**:

- **Default settings**: `A4`, `1200x600 dpi` (`ColorMode=ICM` Pure-K Neutral GCR)
- **Halftoning**:
  - `1200x600 dpi`: True 3-level `{00, 10, 11}` hardware PWM with `11|10` highlight pairing and macro-stripe CIE $L^*$ calibrated LUT (`lut_cmyk_pwm2.dat`)
  - `600x600 dpi`: Calibrated `1x1` micro-dot error diffusion (`lut_cmyk_1x1.dat`) for color and monochrome
- **sRGB / GTK / Browser Gray Handling**: Standards-compliant `cp1025_purek_cmyk.icc` (100% pure K on neutral axis, smooth chroma transition for photos, 1:1 passthrough for native CMYK)
- **Manual Duplex**: Supports `None`, `DuplexNoTumble` (long edge, 180° rotated even pages for both 1-bit & 2-bit), and `DuplexTumble` (short edge)
- **Multi-Size Network Printing**: Emits self-describing per-page `pksmraw`/`pbmraw` frames and auto-infers `ZJI_DMPAPER` so Letter, A5, B5, Photo 4x6/10x15, and Custom sizes print cleanly even when the default queue size is `A4`.

## Install `.deb` on Ubuntu Server 26.04

```bash
sudo apt install ./printer-driver-foo2zjs-cp1025_2026.11.25-1_amd64.deb
sudo lpadmin -p HP_LaserJet_CP_1025 -P /usr/share/ppd/foo2zjs/HP-LaserJet_Pro_CP1025nw.ppd.gz -E
```

## Build from Source (any architecture, e.g., `amd64` / `arm64`)

```bash
make
sudo make install
# Or build a .deb package:
make deb
```
