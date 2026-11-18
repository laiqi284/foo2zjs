/*
 * foo2zjs-dither.c: Full-Page Streaming Halftoner for foo2zjs
 *
 * Converts Ghostscript Netpbm P7 (pamcmyk32) 8-bit continuous tone stream
 * into 1-bit packed bitcmyk format.
 *
 * Modes:
 * - Mode 1 (-m 1, Default): 1x1 Micro-Dots (HP Official Style)
 *   * True 600 DPI individual micro-dots (42.3 um physical size)
 *   * Serpentine 4-tap Floyd-Steinberg error diffusion
 *   * Randomized threshold jitter (HP HPRand equivalent) to break worms
 *   * Zero periodic matrix, completely eliminating 5.4mm grid artifacts
 *   * Pure K enforcement (BlackClears): eliminates composite black underneath K
 * - Mode 2 (-m 2): 2x2 Clustered Dots (High-Density / Vivid)
 *   * 2x2 cluster preservation (84.7 um physical size)
 *   * Hexagonal honeycomb staggered scanning
 *
 * Features:
 * - Multi-plane serpentine scanning
 * - Arbitrary page dimensions (even and odd widths and heights)
 * - Independent CMYK Gamma TRC compensation via command line or config file
 * - Multi-page streaming support with minimal memory footprint (< 1 MB)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <unistd.h>

#define DEFAULT_GAMMA 1.0
#define CONFIG_FILE "/var/tmp/foo2zjs/gamma_stream.conf"
#define DEFAULT_LUT_FILE "/var/tmp/foo2zjs/lut_cmyk_1x1.dat"

#include "embedded_lut.h"

static unsigned char gamma_lut_1x1[4][256];
static unsigned char gamma_lut_2x2[4][256];
static int clean_black = 1;
static int dither_mode = 1; // Default to 1x1 Micro-Dots (HP style)

int load_custom_lut(const char *lut_path) {
    if (!lut_path) return 0;
    FILE *fp = fopen(lut_path, "r");
    if (!fp) return 0;
    int c_v, m_v, y_v, k_v;
    int count = 0;
    for (int i = 0; i < 256; i++) {
        if (fscanf(fp, "%d %d %d %d", &c_v, &m_v, &y_v, &k_v) == 4) {
            gamma_lut_1x1[0][i] = (unsigned char)(c_v < 0 ? 0 : (c_v > 255 ? 255 : c_v));
            gamma_lut_1x1[1][i] = (unsigned char)(m_v < 0 ? 0 : (m_v > 255 ? 255 : m_v));
            gamma_lut_1x1[2][i] = (unsigned char)(y_v < 0 ? 0 : (y_v > 255 ? 255 : y_v));
            gamma_lut_1x1[3][i] = (unsigned char)(k_v < 0 ? 0 : (k_v > 255 ? 255 : k_v));
            count++;
        }
    }
    fclose(fp);
    return (count == 256) ? 1 : 0;
}

void init_gamma_lut_cmyk(double gc, double gm, double gy, double gk) {
    double gammas[4] = {gc, gm, gy, gk};
    for (int c = 0; c < 4; c++) {
        double g = (gammas[c] <= 0.05) ? 1.0 : gammas[c];
        for (int i = 0; i < 256; i++) {
            int base_val = default_calibrated_lut[c][i];
            if (fabs(g - 1.0) > 0.001) {
                double norm = (double)base_val / 255.0;
                double corrected = pow(norm, g);
                int val = (int)(corrected * 255.0 + 0.5);
                if (val < 0) val = 0;
                if (val > 255) val = 255;
                gamma_lut_1x1[c][i] = (unsigned char)val;
            } else {
                gamma_lut_1x1[c][i] = (unsigned char)base_val;
            }
            double norm_lin = (double)i / 255.0;
            int val_lin = (int)(pow(norm_lin, g) * 255.0 + 0.5);
            gamma_lut_2x2[c][i] = (unsigned char)(val_lin < 0 ? 0 : (val_lin > 255 ? 255 : val_lin));
        }
    }
}

// 1x1 Micro-Dot Streaming Error Diffusion (HP Official Style, Pure K, Zero Grid)
int process_pam_page_1x1(FILE *in, FILE *out, int width, int height) {
    int rawbpl = (width + 1) / 2;
    unsigned char *row = malloc(width * 4);
    unsigned char *out_row = malloc(rawbpl);
    if (!row || !out_row) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error\n");
        free(row);
        free(out_row);
        return -1;
    }

    int *err_curr[4], *err_next[4];
    for (int c = 0; c < 4; c++) {
        err_curr[c] = calloc(width + 3, sizeof(int));
        err_next[c] = calloc(width + 3, sizeof(int));
        if (!err_curr[c] || !err_next[c]) {
            fprintf(stderr, "foo2zjs-dither: Memory allocation error for error buffers\n");
            return -1;
        }
    }

    // Pseudo-random state for HP-style threshold jitter
    unsigned int rng = 123456789;

    for (int y = 0; y < height; y++) {
        if (fread(row, 4, width, in) != (size_t)width) break;
        memset(out_row, 0, rawbpl);

        int forward = (y % 2 == 0);
        int start_x = forward ? 0 : (width - 1);
        int end_x = forward ? width : -1;
        int step_x = forward ? 1 : -1;

        for (int c = 0; c < 4; c++) {
            int bit_shift = (c == 0) ? 3 : ((c == 1) ? 2 : ((c == 2) ? 1 : 0));
            for (int x = start_x; x != end_x; x += step_x) {
                int mask = (x % 2 == 0) ? (1 << (bit_shift + 4)) : (1 << bit_shift);
                int v = gamma_lut_1x1[c][row[x * 4 + c]];
                int total = (v << 4) + err_curr[c][x + 1];

                // HP-style threshold perturbation: 128*16 +- jitter
                rng = (1103515245 * rng + 12345) & 0x7fffffff;
                int jitter = (int)((rng % 71) - 35) << 4;
                int th = 2048 + jitter;

                int target = 0;
                if ((out_row[x / 2] & mask) != 0) {
                    // Already set as part of a highlight micro-pair from preceding pixel
                    target = 0;
                } else if (total >= th) {
                    out_row[x / 2] |= mask;
                    int x_next = x + step_x;
                    // Smooth highlight micro-pair blending:
                    // 0-10% (v<=40): 75% micro-pairs + 25% 1x1 dots;
                    // 10-30% (40<v<80): linearly taper micro-pairs from 75% down to 0%;
                    // >=30% (v>=80): 100% pure 1x1 micro-dots.
                    int pair_prob = 0;
                    if (v <= 40) {
                        pair_prob = 75;
                    } else if (v < 80) {
                        pair_prob = (75 * (80 - v)) / 40;
                    }
                    rng = (1103515245 * rng + 12345) & 0x7fffffff;
                    if (pair_prob > 0 && ((int)(rng % 100) < pair_prob) && x_next >= 0 && x_next < width) {
                        int mask_next = (x_next % 2 == 0) ? (1 << (bit_shift + 4)) : (1 << bit_shift);
                        out_row[x_next / 2] |= mask_next;
                        target = (255 << 4) * 2;
                    } else {
                        target = 255 << 4;
                    }
                }
                int err = total - target;

                // Floyd-Steinberg error distribution:
                // 7/16 forward, 3/16 diag-back, 5/16 down, 1/16 diag-forward
                if (forward) {
                    err_curr[c][x + 2] += (err * 7) / 16;
                    err_next[c][x + 0] += (err * 3) / 16;
                    err_next[c][x + 1] += (err * 5) / 16;
                    err_next[c][x + 2] += (err * 1) / 16;
                } else {
                    err_curr[c][x + 0] += (err * 7) / 16;
                    err_next[c][x + 2] += (err * 3) / 16;
                    err_next[c][x + 1] += (err * 5) / 16;
                    err_next[c][x + 0] += (err * 1) / 16;
                }
            }
        }

        // Clean Black / BlackClears: If Black dot is printed, clear C, M, Y underneath
        if (clean_black) {
            for (int x = 0; x < width; x += 2) {
                unsigned char b = out_row[x / 2];
                if (b & 0x10) b &= 0x1F; // clear high nibble CMY
                if (b & 0x01) b &= 0xF1; // clear low nibble CMY
                out_row[x / 2] = b;
            }
        }

        if (fwrite(out_row, 1, rawbpl, out) != (size_t)rawbpl) break;

        for (int c = 0; c < 4; c++) {
            memset(err_curr[c], 0, (width + 3) * sizeof(int));
            int *tmp = err_curr[c];
            err_curr[c] = err_next[c];
            err_next[c] = tmp;
        }
    }

    for (int c = 0; c < 4; c++) {
        free(err_curr[c]);
        free(err_next[c]);
    }
    free(row);
    free(out_row);
    return 0;
}

// 2x2 Clustered Streaming Error Diffusion (Honeycomb Staggered 2x2, Vivid)
int process_pam_page_2x2(FILE *in, FILE *out, int width, int height) {
    int cw = (width + 1) / 2;
    int ch = (height + 1) / 2;
    int rawbpl = (width + 1) / 2;

    unsigned char *row0 = malloc(width * 4);
    unsigned char *row1 = malloc(width * 4);
    unsigned char *out_y0 = malloc(rawbpl);
    unsigned char *out_y1 = malloc(rawbpl);

    if (!row0 || !row1 || !out_y0 || !out_y1) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error\n");
        free(row0); free(row1); free(out_y0); free(out_y1);
        return -1;
    }

    int *err_curr[4], *err_next[4];
    for (int c = 0; c < 4; c++) {
        err_curr[c] = calloc(cw + 3, sizeof(int));
        err_next[c] = calloc(cw + 3, sizeof(int));
    }

    int cur_y = 0;
    for (int cy = 0; cy < ch; cy++) {
        if (fread(row0, 4, width, in) != (size_t)width) break;
        cur_y++;

        int has_row1 = 0;
        if (cur_y < height) {
            if (fread(row1, 4, width, in) == (size_t)width) {
                has_row1 = 1;
                cur_y++;
            } else {
                memcpy(row1, row0, width * 4);
            }
        } else {
            memcpy(row1, row0, width * 4);
        }

        memset(out_y0, 0, rawbpl);
        memset(out_y1, 0, rawbpl);

        int shift = (cy % 2 == 1) ? 1 : 0;
        int forward = (cy % 2 == 0);
        int start_cx = forward ? 0 : (cw - 1);
        int end_cx = forward ? cw : -1;
        int step_cx = forward ? 1 : -1;

        for (int ch_idx = 0; ch_idx < 4; ch_idx++) {
            for (int cx = start_cx; cx != end_cx; cx += step_cx) {
                int x0 = 2 * cx + shift;
                int x1 = x0 + 1;
                if (x0 >= width) x0 = width - 1;
                if (x1 >= width) x1 = width - 1;

                int v00 = gamma_lut_2x2[ch_idx][row0[x0 * 4 + ch_idx]];
                int v01 = gamma_lut_2x2[ch_idx][row0[x1 * 4 + ch_idx]];
                int v10 = gamma_lut_2x2[ch_idx][row1[x0 * 4 + ch_idx]];
                int v11 = gamma_lut_2x2[ch_idx][row1[x1 * 4 + ch_idx]];
                int cell_val = (v00 + v01 + v10 + v11) / 4;

                int total = (cell_val << 4) + err_curr[ch_idx][cx + 1];

                int out_bit = 0;
                int target_scaled = 0;
                if (total >= 2048) {
                    out_bit = 1;
                    target_scaled = 255 << 4;
                }
                int err = total - target_scaled;

                if (out_bit) {
                    int bit_shift = (ch_idx == 0) ? 3 : ((ch_idx == 1) ? 2 : ((ch_idx == 2) ? 1 : 0));
                    int mask0 = (x0 % 2 == 0) ? (1 << (bit_shift + 4)) : (1 << bit_shift);
                    int mask1 = (x1 % 2 == 0) ? (1 << (bit_shift + 4)) : (1 << bit_shift);

                    out_y0[x0 / 2] |= mask0;
                    out_y0[x1 / 2] |= mask1;
                    if (has_row1) {
                        out_y1[x0 / 2] |= mask0;
                        out_y1[x1 / 2] |= mask1;
                    }
                }

                if (forward) {
                    err_curr[ch_idx][cx + 2] += (err * 7) / 16;
                    err_next[ch_idx][cx + 0] += (err * 3) / 16;
                    err_next[ch_idx][cx + 1] += (err * 5) / 16;
                    err_next[ch_idx][cx + 2] += (err * 1) / 16;
                } else {
                    err_curr[ch_idx][cx + 0] += (err * 7) / 16;
                    err_next[ch_idx][cx + 2] += (err * 3) / 16;
                    err_next[ch_idx][cx + 1] += (err * 5) / 16;
                    err_next[ch_idx][cx + 0] += (err * 1) / 16;
                }
            }
        }

        // Clean Black / BlackClears for 2x2 cluster
        if (clean_black) {
            for (int x = 0; x < width; x += 2) {
                unsigned char b0 = out_y0[x / 2];
                if (b0 & 0x10) b0 &= 0x1F;
                if (b0 & 0x01) b0 &= 0xF1;
                out_y0[x / 2] = b0;

                if (has_row1) {
                    unsigned char b1 = out_y1[x / 2];
                    if (b1 & 0x10) b1 &= 0x1F;
                    if (b1 & 0x01) b1 &= 0xF1;
                    out_y1[x / 2] = b1;
                }
            }
        }

        if (fwrite(out_y0, 1, rawbpl, out) != (size_t)rawbpl) break;
        if (has_row1) {
            if (fwrite(out_y1, 1, rawbpl, out) != (size_t)rawbpl) break;
        }

        for (int c = 0; c < 4; c++) {
            memset(err_curr[c], 0, (cw + 3) * sizeof(int));
            int *tmp = err_curr[c];
            err_curr[c] = err_next[c];
            err_next[c] = tmp;
        }
    }

    for (int c = 0; c < 4; c++) {
        free(err_curr[c]);
        free(err_next[c]);
    }
    free(row0);
    free(row1);
    free(out_y0);
    free(out_y1);
    return 0;
}

// Split Half-and-Half Page (Top Half 1x1 Micro-Dots, Bottom Half 2x2 Clustered Dots)
int process_pam_page_split(FILE *in, FILE *out, int width, int height) {
    int height1 = (height / 2) & ~1;
    int height2 = height - height1;

    int rc1 = process_pam_page_1x1(in, out, width, height1);
    if (rc1 != 0) return rc1;
    int rc2 = process_pam_page_2x2(in, out, width, height2);
    return rc2;
}

int process_pam_page(FILE *in, FILE *out) {
    char line[256];
    int width = 0, height = 0, depth = 0, maxval = 0;

    // Read P7 PAM header
    if (!fgets(line, sizeof(line), in)) return EOF;
    while (line[0] == '\n' || line[0] == '\r' || line[0] == ' ' || line[0] == '\t') {
        if (!fgets(line, sizeof(line), in)) return EOF;
    }
    if (strncmp(line, "P7", 2) != 0) {
        fprintf(stderr, "foo2zjs-dither: Not a P7 PAM header: %s\n", line);
        return -1;
    }

    while (fgets(line, sizeof(line), in)) {
        if (strncmp(line, "WIDTH", 5) == 0) sscanf(line + 5, "%d", &width);
        else if (strncmp(line, "HEIGHT", 6) == 0) sscanf(line + 6, "%d", &height);
        else if (strncmp(line, "DEPTH", 5) == 0) sscanf(line + 5, "%d", &depth);
        else if (strncmp(line, "MAXVAL", 6) == 0) sscanf(line + 6, "%d", &maxval);
        else if (strncmp(line, "ENDHDR", 6) == 0) break;
    }

    if (width <= 0 || height <= 0 || depth != 4) {
        fprintf(stderr, "foo2zjs-dither: Invalid PAM geometry: %dx%d depth=%d\n", width, height, depth);
        return -1;
    }

    if (dither_mode == 1) {
        return process_pam_page_1x1(in, out, width, height);
    } else if (dither_mode == 3) {
        return process_pam_page_split(in, out, width, height);
    } else {
        return process_pam_page_2x2(in, out, width, height);
    }
}

int main(int argc, char *argv[]) {
    double gc = DEFAULT_GAMMA, gm = DEFAULT_GAMMA, gy = DEFAULT_GAMMA, gk = DEFAULT_GAMMA;
    const char *cfg_path = CONFIG_FILE;

    // Check config file first
    FILE *cfp = fopen(cfg_path, "r");
    if (cfp) {
        double g1, g2, g3, g4;
        int n = fscanf(cfp, "%lf %lf %lf %lf", &g1, &g2, &g3, &g4);
        if (n == 4) {
            gc = g1; gm = g2; gy = g3; gk = g4;
        } else if (n >= 1) {
            gc = gm = gy = gk = g1;
        }
        fclose(cfp);
    }

    const char *lut_path = NULL;
    int lut_explicitly_set = 0;

    // Parse command line options
    int opt;
    while ((opt = getopt(argc, argv, "m:g:c:l:B:h")) != -1) {
        switch (opt) {
            case 'm':
                dither_mode = atoi(optarg);
                if (dither_mode < 1 || dither_mode > 3) dither_mode = 1;
                break;
            case 'B':
                clean_black = atoi(optarg);
                break;
            case 'l':
                lut_explicitly_set = 1;
                if (strcmp(optarg, "none") == 0 || strcmp(optarg, "raw") == 0 || strcmp(optarg, "linear") == 0) {
                    lut_path = NULL;
                } else {
                    lut_path = optarg;
                }
                break;
            case 'g': {
                double g1, g2, g3, g4;
                int n = sscanf(optarg, "%lf,%lf,%lf,%lf", &g1, &g2, &g3, &g4);
                if (n == 4) {
                    gc = g1; gm = g2; gy = g3; gk = g4;
                } else {
                    gc = gm = gy = gk = atof(optarg);
                }
                break;
            }
            case 'c':
                cfg_path = optarg;
                cfp = fopen(cfg_path, "r");
                if (cfp) {
                    double g1, g2, g3, g4;
                    int n = fscanf(cfp, "%lf %lf %lf %lf", &g1, &g2, &g3, &g4);
                    if (n == 4) {
                        gc = g1; gm = g2; gy = g3; gk = g4;
                    } else if (n >= 1) {
                        gc = gm = gy = gk = g1;
                    }
                    fclose(cfp);
                }
                break;
            case 'h':
                fprintf(stderr, "Usage: %s [-m 1|2|3] [-B 0|1] [-l lut_file|none] [-g gamma|gc,gm,gy,gk] [-c config_file]\n", argv[0]);
                fprintf(stderr, "  -m 1: 1x1 Micro-Dots (HP style ultra-fine, default)\n");
                fprintf(stderr, "  -m 2: 2x2 Clustered Dots (honeycomb vivid)\n");
                fprintf(stderr, "  -m 3: Split Comparison (Top half 1x1, Bottom half 2x2)\n");
                fprintf(stderr, "  -B 1: Pure Black enforcement (BlackClears, default)\n");
                fprintf(stderr, "  -l file: CMYK LUT file (or 'none' for pure linear)\n");
                return 0;
        }
    }

    // Default LUT handling:
    // Auto-load calibrated LUT for 1x1 (mode 1 and top half of mode 3 split)
    // Mode 2 (2x2) always stays pure linear reference baseline.
    if (!lut_explicitly_set && (dither_mode == 1 || dither_mode == 3)) {
        if (access(DEFAULT_LUT_FILE, R_OK) == 0) {
            lut_path = DEFAULT_LUT_FILE;
        }
    }

    init_gamma_lut_cmyk(gc, gm, gy, gk);

    if (lut_path && load_custom_lut(lut_path)) {
        fprintf(stderr, "foo2zjs-dither: Loaded custom 1x1 CMYK LUT from %s\n", lut_path);
    } else {
        fprintf(stderr, "foo2zjs-dither: Using built-in calibrated 1x1 CMYK LUT (Job 216)\n");
    }

    // Process all pages until stdin EOF
    while (!feof(stdin)) {
        int rc = process_pam_page(stdin, stdout);
        if (rc == EOF) break;
        if (rc < 0) return 1;
    }

    return 0;
}
