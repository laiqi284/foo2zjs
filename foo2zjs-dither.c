/*
 * foo2zjs-dither.c: Dedicated Streaming Halftoner for HP LaserJet Pro CP1025/CP1025nw
 *
 * Converts Ghostscript Netpbm P7 (pamcmyk32) 8-bit continuous tone CMYK stream
 * into pksmraw (4 x P4 planar bitmaps) for 600x600 1-bit or 1200x600 2-bit {00,10,11} PWM,
 * and converts P5 (pgmraw) grayscale stream into P4 bitmap for monochrome printing.
 *
 * Modes:
 * - 600x600 (-p 1): 1x1 Micro-Dots (42.3 um) with 5-22% highlight micro-pair blending
 * - 1200x600 (-p 2): 3-Level Hardware PWM {00, 10, 11} with unbroken 11|10 highlight pairing
 *   and CIE L* macro-stripe self-calibrated LUT.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <unistd.h>

#define DEFAULT_GAMMA 1.0
#define DEFAULT_LUT_FILE "/usr/share/foo2zjs/crd/zjs/lut_cmyk_1x1.dat"
#define DEFAULT_PWM2_LUT_FILE "/usr/share/foo2zjs/crd/zjs/lut_cmyk_pwm2.dat"

#include "embedded_lut.h"
#include "embedded_lut_pwm2.h"

static unsigned char gamma_lut_1x1[4][256];
static int clean_black = 0;
static int dither_mode = 1;
static int pwm_bpp = 1;     /* 1: 600x600 1-bit, 2: 1200x600 2-bit {00,10,11} PWM */

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
            int base_val = (pwm_bpp == 2) ? default_calibrated_lut_pwm2[c][i] : default_calibrated_lut[c][i];
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
        }
    }
}

// 1x1 Micro-Dot Error Diffusion (600x600 1-bit -> pksmraw: 4 x P4 planes per page)
int process_pam_page_1x1(FILE *in, FILE *out, int width, int height) {
    int bpl = (width + 7) / 8;
    unsigned char *row = malloc((size_t)width * 4);
    unsigned char *dot_row[4] = {NULL, NULL, NULL, NULL};
    unsigned char *planes[4] = {NULL, NULL, NULL, NULL};
    int *err_curr[4] = {NULL, NULL, NULL, NULL};
    int *err_next[4] = {NULL, NULL, NULL, NULL};

    for (int c = 0; c < 4; c++) {
        dot_row[c] = malloc((size_t)width);
        planes[c] = calloc((size_t)bpl * height, 1);
        err_curr[c] = calloc((size_t)width + 3, sizeof(int));
        err_next[c] = calloc((size_t)width + 3, sizeof(int));
    }
    if (!row || !dot_row[0] || !dot_row[1] || !dot_row[2] || !dot_row[3] ||
        !planes[0] || !planes[1] || !planes[2] || !planes[3] ||
        !err_curr[0] || !err_curr[1] || !err_curr[2] || !err_curr[3] ||
        !err_next[0] || !err_next[1] || !err_next[2] || !err_next[3]) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error\n");
        free(row);
        for (int c = 0; c < 4; c++) {
            free(dot_row[c]); free(planes[c]); free(err_curr[c]); free(err_next[c]);
        }
        return -1;
    }

    unsigned int rng = 123456789u;

    for (int y = 0; y < height; y++) {
        if (fread(row, 4, (size_t)width, in) != (size_t)width) break;
        for (int c = 0; c < 4; c++) memset(dot_row[c], 0, (size_t)width);

        int forward = (y % 2 == 0);
        int start_x = forward ? 0 : (width - 1);
        int end_x = forward ? width : -1;
        int step_x = forward ? 1 : -1;

        for (int c = 0; c < 4; c++) {
            for (int x = start_x; x != end_x; x += step_x) {
                int v = gamma_lut_1x1[c][row[x * 4 + c]];
                int total = (v << 4) + err_curr[c][x + 1];

                rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                int jitter = (int)((rng % 71) - 35) << 4;
                int th = 2048 + jitter;

                int target = 0;
                if (dot_row[c][x] != 0) {
                    target = 0;
                } else if (total >= th) {
                    dot_row[c][x] = 1;
                    int x_next = x + step_x;
                    int pair_prob = 0;
                    if (v <= 22) {
                        pair_prob = 75;
                    } else if (v < 80) {
                        pair_prob = (75 * (80 - v)) / 58;
                    }
                    rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                    if (pair_prob > 0 && ((int)(rng % 100) < pair_prob) && x_next >= 0 && x_next < width) {
                        dot_row[c][x_next] = 1;
                        target = (255 << 4) * 2;
                    } else {
                        target = 255 << 4;
                    }
                }
                int err = total - target;

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

        if (clean_black) {
            for (int x = 0; x < width; x++) {
                if (dot_row[3][x]) {
                    dot_row[0][x] = 0;
                    dot_row[1][x] = 0;
                    dot_row[2][x] = 0;
                }
            }
        }

        for (int c = 0; c < 4; c++) {
            unsigned char *dst = planes[c] + (size_t)y * bpl;
            for (int x = 0; x < width; x++) {
                if (dot_row[c][x]) {
                    dst[x >> 3] |= (unsigned char)(0x80 >> (x & 7));
                }
            }
            memset(err_curr[c], 0, ((size_t)width + 3) * sizeof(int));
            int *tmp = err_curr[c];
            err_curr[c] = err_next[c];
            err_next[c] = tmp;
        }
    }

    for (int c = 0; c < 4; c++) {
        fprintf(out, "P4\n%d %d\n", width, height);
        if (fwrite(planes[c], 1, (size_t)bpl * height, out) != (size_t)bpl * height) break;
    }

    for (int c = 0; c < 4; c++) {
        free(dot_row[c]);
        free(planes[c]);
        free(err_curr[c]);
        free(err_next[c]);
    }
    free(row);
    return 0;
}

// True 3-Level Hardware PWM ({00, 10, 11}) Error Diffusion for 1200x600dpi (pksmraw: 4 x P4 planes per page)
int process_pam_page_pwm2(FILE *in, FILE *out, int width, int height) {
    int bpl = (width * 2 + 7) / 8;
    unsigned char *row = malloc((size_t)width * 4);
    unsigned char *code_row[4] = {NULL, NULL, NULL, NULL};
    unsigned char *planes[4] = {NULL, NULL, NULL, NULL};
    int *err_curr[4] = {NULL, NULL, NULL, NULL};
    int *err_next[4] = {NULL, NULL, NULL, NULL};

    for (int c = 0; c < 4; c++) {
        code_row[c] = malloc((size_t)width);
        planes[c] = calloc((size_t)bpl * height, 1);
        err_curr[c] = calloc((size_t)width + 3, sizeof(int));
        err_next[c] = calloc((size_t)width + 3, sizeof(int));
    }
    if (!row || !code_row[0] || !code_row[1] || !code_row[2] || !code_row[3] ||
        !planes[0] || !planes[1] || !planes[2] || !planes[3] ||
        !err_curr[0] || !err_curr[1] || !err_curr[2] || !err_curr[3] ||
        !err_next[0] || !err_next[1] || !err_next[2] || !err_next[3]) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error\n");
        free(row);
        for (int c = 0; c < 4; c++) {
            free(code_row[c]); free(planes[c]); free(err_curr[c]); free(err_next[c]);
        }
        return -1;
    }

    const int lvl_mid = 192 << 4; // 3072
    const int lvl_full = 255 << 4; // 4080
    unsigned int rng = 123456789u;

    for (int y = 0; y < height; y++) {
        if (fread(row, 4, (size_t)width, in) != (size_t)width) break;
        for (int c = 0; c < 4; c++) memset(code_row[c], 0, (size_t)width);

        int forward = (y % 2 == 0);
        int start_x = forward ? 0 : (width - 1);
        int end_x = forward ? width : -1;
        int step_x = forward ? 1 : -1;

        for (int c = 0; c < 4; c++) {
            for (int x = start_x; x != end_x; x += step_x) {
                int v = gamma_lut_1x1[c][row[x * 4 + c]];
                int total = (v << 4) + err_curr[c][x + 1];

                rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                int jitter1 = (int)((rng % 113) - 56) << 4;
                int th1 = (96 << 4) + jitter1;

                rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                int jitter2 = (int)((rng % 49) - 24) << 4;
                int th2 = (224 << 4) + jitter2;

                int target = 0;
                if (code_row[c][x] != 0) {
                    target = 0;
                } else if (total >= th2) {
                    code_row[c][x] = 3;
                    target = lvl_full;
                } else if (total >= th1) {
                    int x_next = x + step_x;
                    int pair_prob = 0;
                    if (v <= 28) {
                        pair_prob = 85;
                    } else if (v < 72) {
                        pair_prob = (85 * (72 - v)) / 44;
                    }
                    rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                    if (pair_prob > 0 && ((int)(rng % 100) < pair_prob) &&
                        x_next >= 0 && x_next < width && code_row[c][x_next] == 0) {
                        // Continuous 3-subpixel pulse (11 | 10 = 1 1 1 0 in left-to-right laser scan order)
                        if (forward) {
                            code_row[c][x] = 3;
                            code_row[c][x_next] = 2;
                        } else {
                            code_row[c][x] = 2;
                            code_row[c][x_next] = 3;
                        }
                        target = lvl_full + lvl_mid;
                    } else {
                        code_row[c][x] = 2;
                        target = lvl_mid;
                    }
                }
                int err = total - target;

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

        if (clean_black) {
            for (int x = 0; x < width; x++) {
                if (code_row[3][x] != 0) {
                    code_row[0][x] = 0;
                    code_row[1][x] = 0;
                    code_row[2][x] = 0;
                }
            }
        }

        for (int c = 0; c < 4; c++) {
            unsigned char *dst = planes[c] + (size_t)y * bpl;
            for (int x = 0; x < width; x++) {
                unsigned char code = code_row[c][x];
                if (code != 0) {
                    dst[x >> 2] |= (unsigned char)(code << (6 - 2 * (x & 3)));
                }
            }
            memset(err_curr[c], 0, ((size_t)width + 3) * sizeof(int));
            int *tmp = err_curr[c];
            err_curr[c] = err_next[c];
            err_next[c] = tmp;
        }
    }

    for (int c = 0; c < 4; c++) {
        fprintf(out, "P4\n%d %d\n", width * 2, height);
        if (fwrite(planes[c], 1, (size_t)bpl * height, out) != (size_t)bpl * height) break;
    }

    for (int c = 0; c < 4; c++) {
        free(code_row[c]);
        free(planes[c]);
        free(err_curr[c]);
        free(err_next[c]);
    }
    free(row);
    return 0;
}

// Read next ASCII decimal integer from a PNM (P5 PGM) header, skipping comments and a single trailing whitespace
static int read_pnm_int(FILE *in) {
    int c;
    while ((c = fgetc(in)) != EOF) {
        if (c == '#') {
            while ((c = fgetc(in)) != EOF && c != '\n') {}
        } else if (c == ' ' || c == '\t' || c == '\r' || c == '\n') {
            continue;
        } else {
            break;
        }
    }
    if (c < '0' || c > '9') return -1;
    int val = 0;
    while (c >= '0' && c <= '9') {
        val = val * 10 + (c - '0');
        c = fgetc(in);
    }
    if (c != EOF && c != ' ' && c != '\t' && c != '\r' && c != '\n') {
        ungetc(c, in);
    }
    return val;
}

// Monochrome 600x600 1-bit (P5 PGM -> P4 PBM) using tuned K-channel LUT and 5-22% highlight blending
int process_pgm_page_1x1(FILE *in, FILE *out, int width, int height) {
    int bpl = (width + 7) / 8;
    unsigned char *row = malloc((size_t)width);
    unsigned char *dot_row = malloc((size_t)width);
    unsigned char *out_row = malloc((size_t)bpl);
    if (!row || !dot_row || !out_row) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error\n");
        free(row); free(dot_row); free(out_row);
        return -1;
    }

    int *err_curr = calloc((size_t)width + 3, sizeof(int));
    int *err_next = calloc((size_t)width + 3, sizeof(int));
    if (!err_curr || !err_next) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error for error buffers\n");
        free(err_curr); free(err_next);
        free(row); free(dot_row); free(out_row);
        return -1;
    }

    fprintf(out, "P4\n%d %d\n", width, height);
    unsigned int rng = 123456789u;

    for (int y = 0; y < height; y++) {
        if (fread(row, 1, (size_t)width, in) != (size_t)width) break;
        memset(dot_row, 0, (size_t)width);
        memset(out_row, 0, (size_t)bpl);

        int forward = (y % 2 == 0);
        int start_x = forward ? 0 : (width - 1);
        int end_x = forward ? width : -1;
        int step_x = forward ? 1 : -1;

        for (int x = start_x; x != end_x; x += step_x) {
            int k_in = 255 - (int)row[x];
            int v = gamma_lut_1x1[3][k_in];
            int total = (v << 4) + err_curr[x + 1];

            rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
            int jitter = (int)((rng % 71) - 35) << 4;
            int th = 2048 + jitter;

            int target = 0;
            if (dot_row[x]) {
                target = 0;
            } else if (total >= th) {
                dot_row[x] = 1;
                int x_next = x + step_x;
                int pair_prob = 0;
                if (v <= 22) {
                    pair_prob = 75;
                } else if (v < 80) {
                    pair_prob = (75 * (80 - v)) / 58;
                }
                rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                if (pair_prob > 0 && ((int)(rng % 100) < pair_prob) &&
                    x_next >= 0 && x_next < width && !dot_row[x_next]) {
                    dot_row[x_next] = 1;
                    target = (255 << 4) * 2;
                } else {
                    target = 255 << 4;
                }
            }
            int err = total - target;

            if (forward) {
                err_curr[x + 2] += (err * 7) / 16;
                err_next[x + 0] += (err * 3) / 16;
                err_next[x + 1] += (err * 5) / 16;
                err_next[x + 2] += (err * 1) / 16;
            } else {
                err_curr[x + 0] += (err * 7) / 16;
                err_next[x + 2] += (err * 3) / 16;
                err_next[x + 1] += (err * 5) / 16;
                err_next[x + 0] += (err * 1) / 16;
            }
        }

        for (int x = 0; x < width; x++) {
            if (dot_row[x]) {
                out_row[x >> 3] |= (unsigned char)(0x80 >> (x & 7));
            }
        }
        if (fwrite(out_row, 1, (size_t)bpl, out) != (size_t)bpl) break;

        memset(err_curr, 0, ((size_t)width + 3) * sizeof(int));
        int *tmp = err_curr; err_curr = err_next; err_next = tmp;
    }

    free(err_curr); free(err_next);
    free(row); free(dot_row); free(out_row);
    return 0;
}

// Monochrome 1200x600 3-Level {00, 10, 11} Hardware PWM (P5 PGM -> P4 2-bit-packed PBM)
int process_pgm_page_pwm2(FILE *in, FILE *out, int width, int height) {
    int bpl = (width * 2 + 7) / 8;
    unsigned char *row = malloc((size_t)width);
    unsigned char *code_row = malloc((size_t)width);
    unsigned char *out_row = malloc((size_t)bpl);
    if (!row || !code_row || !out_row) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error\n");
        free(row); free(code_row); free(out_row);
        return -1;
    }

    int *err_curr = calloc((size_t)width + 3, sizeof(int));
    int *err_next = calloc((size_t)width + 3, sizeof(int));
    if (!err_curr || !err_next) {
        fprintf(stderr, "foo2zjs-dither: Memory allocation error for error buffers\n");
        free(err_curr); free(err_next);
        free(row); free(code_row); free(out_row);
        return -1;
    }

    fprintf(out, "P4\n%d %d\n", width * 2, height);
    const int lvl_mid = 192 << 4;
    const int lvl_full = 255 << 4;
    unsigned int rng = 123456789u;

    for (int y = 0; y < height; y++) {
        if (fread(row, 1, (size_t)width, in) != (size_t)width) break;
        memset(code_row, 0, (size_t)width);
        memset(out_row, 0, (size_t)bpl);

        int forward = (y % 2 == 0);
        int start_x = forward ? 0 : (width - 1);
        int end_x = forward ? width : -1;
        int step_x = forward ? 1 : -1;

        for (int x = start_x; x != end_x; x += step_x) {
            int k_in = 255 - (int)row[x];
            int v = gamma_lut_1x1[3][k_in];
            int total = (v << 4) + err_curr[x + 1];

            rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
            int jitter1 = (int)((rng % 113) - 56) << 4;
            int th1 = (96 << 4) + jitter1;

            rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
            int jitter2 = (int)((rng % 49) - 24) << 4;
            int th2 = (224 << 4) + jitter2;

            int target = 0;
            if (code_row[x] != 0) {
                target = 0;
            } else if (total >= th2) {
                code_row[x] = 3;
                target = lvl_full;
            } else if (total >= th1) {
                int x_next = x + step_x;
                int pair_prob = 0;
                if (v <= 28) {
                    pair_prob = 85;
                } else if (v < 72) {
                    pair_prob = (85 * (72 - v)) / 44;
                }
                rng = (1103515245u * rng + 12345u) & 0x7fffffffu;
                if (pair_prob > 0 && ((int)(rng % 100) < pair_prob) &&
                    x_next >= 0 && x_next < width && code_row[x_next] == 0) {
                    // Continuous 3-subpixel pulse (11 | 10 = 1 1 1 0 in left-to-right laser scan order)
                    if (forward) {
                        code_row[x] = 3;
                        code_row[x_next] = 2;
                    } else {
                        code_row[x] = 2;
                        code_row[x_next] = 3;
                    }
                    target = lvl_full + lvl_mid;
                } else {
                    code_row[x] = 2;
                    target = lvl_mid;
                }
            }
            int err = total - target;

            if (forward) {
                err_curr[x + 2] += (err * 7) / 16;
                err_next[x + 0] += (err * 3) / 16;
                err_next[x + 1] += (err * 5) / 16;
                err_next[x + 2] += (err * 1) / 16;
            } else {
                err_curr[x + 0] += (err * 7) / 16;
                err_next[x + 2] += (err * 3) / 16;
                err_next[x + 1] += (err * 5) / 16;
                err_next[x + 0] += (err * 1) / 16;
            }
        }

        for (int x = 0; x < width; x++) {
            unsigned char code = code_row[x];
            if (code != 0) {
                out_row[x >> 2] |= (unsigned char)(code << (6 - 2 * (x & 3)));
            }
        }
        if (fwrite(out_row, 1, (size_t)bpl, out) != (size_t)bpl) break;

        memset(err_curr, 0, ((size_t)width + 3) * sizeof(int));
        int *tmp = err_curr; err_curr = err_next; err_next = tmp;
    }

    free(err_curr); free(err_next);
    free(row); free(code_row); free(out_row);
    return 0;
}

int process_pam_page(FILE *in, FILE *out) {
    char line[256];
    int width = 0, height = 0, depth = 0, maxval = 0;

    if (!fgets(line, sizeof(line), in)) return EOF;
    while (line[0] == '\n' || line[0] == '\r' || line[0] == ' ' || line[0] == '\t') {
        if (!fgets(line, sizeof(line), in)) return EOF;
    }
    if (strncmp(line, "P5", 2) == 0) {
        int n = sscanf(line + 2, "%d %d %d", &width, &height, &maxval);
        if (n < 1) width = read_pnm_int(in);
        if (n < 2) height = read_pnm_int(in);
        if (n < 3) maxval = read_pnm_int(in);
        if (width <= 0 || height <= 0 || maxval != 255) {
            fprintf(stderr, "foo2zjs-dither: Invalid PGM geometry: %dx%d maxval=%d\n", width, height, maxval);
            return -1;
        }
        if (pwm_bpp == 2) {
            return process_pgm_page_pwm2(in, out, width, height);
        }
        return process_pgm_page_1x1(in, out, width, height);
    }
    if (strncmp(line, "P7", 2) != 0) {
        fprintf(stderr, "foo2zjs-dither: Not a P7 PAM or P5 PGM header: %s\n", line);
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

    if (pwm_bpp == 2) {
        return process_pam_page_pwm2(in, out, width, height);
    }
    return process_pam_page_1x1(in, out, width, height);
}

int main(int argc, char *argv[]) {
    double gc = DEFAULT_GAMMA, gm = DEFAULT_GAMMA, gy = DEFAULT_GAMMA, gk = DEFAULT_GAMMA;
    const char *lut_path = NULL;
    int lut_explicitly_set = 0;

    int opt;
    while ((opt = getopt(argc, argv, "m:p:g:l:B:h")) != -1) {
        switch (opt) {
            case 'm':
                dither_mode = atoi(optarg);
                if (dither_mode != 1) {
                    fprintf(stderr, "foo2zjs-dither: Only 1x1 micro-dot mode (-m 1) is supported; using mode 1\n");
                    dither_mode = 1;
                }
                break;
            case 'p':
                pwm_bpp = atoi(optarg);
                if (pwm_bpp != 2) pwm_bpp = 1;
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
            case 'h':
                fprintf(stderr, "Usage: %s [-m 1] [-p 1|2] [-B 0|1] [-l lut_file|none] [-g gamma|gc,gm,gy,gk]\n", argv[0]);
                fprintf(stderr, "  -m 1: 1x1 Micro-Dots (CP1025 dedicated, default)\n");
                fprintf(stderr, "  -p 1|2: 1=600x600 1-bit (default), 2=1200x600 2-bit {00,10,11} PWM\n");
                fprintf(stderr, "  -B 0|1: Pure Black enforcement (BlackClears, default 0)\n");
                fprintf(stderr, "  -l file: CMYK LUT file (or 'none' for built-in calibrated LUT)\n");
                return 0;
        }
    }

    if (!lut_explicitly_set) {
        const char *default_lut = (pwm_bpp == 2) ? DEFAULT_PWM2_LUT_FILE : DEFAULT_LUT_FILE;
        if (access(default_lut, R_OK) == 0) {
            lut_path = default_lut;
        }
    }

    init_gamma_lut_cmyk(gc, gm, gy, gk);

    if (lut_path && load_custom_lut(lut_path)) {
        fprintf(stderr, "foo2zjs-dither: Loaded custom %s CMYK LUT from %s\n",
                (pwm_bpp == 2) ? "PWM2" : "1x1", lut_path);
    } else {
        fprintf(stderr, "foo2zjs-dither: Using built-in calibrated %s CMYK LUT\n",
                (pwm_bpp == 2) ? "PWM2" : "1x1");
    }

    while (!feof(stdin)) {
        int rc = process_pam_page(stdin, stdout);
        if (rc == EOF) break;
        if (rc < 0) return 1;
    }

    return 0;
}
