#!/usr/bin/env python3
"""
Generate a native 4-channel CMYK ICC Profile (hp-cp1025-cmyk.icc)
from hp-cp1025-rgb-392-bpp1.icm for modern Ghostscript 10.x.
"""

import ctypes
import os
import sys

# Load LittleCMS 2
lcms = ctypes.CDLL('liblcms2.so.2')

# Setup types
cmsHPROFILE = ctypes.c_void_p
cmsHTRANSFORM = ctypes.c_void_p
cmsStage = ctypes.c_void_p
cmsPipeline = ctypes.c_void_p
cmsMLU = ctypes.c_void_p

SAMPLER_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16), ctypes.c_void_p)
ERROR_LOGGER = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p)

def py_error_logger(ctx, error_code, text):
    print(f"LCMS ERROR [{error_code}]: {text.decode('latin1', 'ignore')}", file=sys.stderr)

logger_cb = ERROR_LOGGER(py_error_logger)
lcms.cmsSetLogErrorHandler(logger_cb)

# LCMS functions
lcms.cmsCreateProfilePlaceholder.restype = cmsHPROFILE
lcms.cmsCreateLab4Profile.restype = cmsHPROFILE
lcms.cmsOpenProfileFromFile.restype = cmsHPROFILE
lcms.cmsOpenProfileFromFile.argtypes = [ctypes.c_char_p, ctypes.c_char_p]

lcms.cmsCreateTransform.restype = cmsHTRANSFORM
lcms.cmsCreateTransform.argtypes = [cmsHPROFILE, ctypes.c_uint32, cmsHPROFILE, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
lcms.cmsDeleteTransform.argtypes = [cmsHTRANSFORM]
lcms.cmsDoTransform.argtypes = [cmsHTRANSFORM, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]

lcms.cmsSetProfileVersion.argtypes = [cmsHPROFILE, ctypes.c_double]
lcms.cmsSetColorSpace.argtypes = [cmsHPROFILE, ctypes.c_uint32]
lcms.cmsSetPCS.argtypes = [cmsHPROFILE, ctypes.c_uint32]
lcms.cmsSetDeviceClass.argtypes = [cmsHPROFILE, ctypes.c_uint32]

lcms.cmsPipelineAlloc.restype = cmsPipeline
lcms.cmsPipelineAlloc.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
lcms.cmsPipelineInsertStage.argtypes = [cmsPipeline, ctypes.c_int, cmsStage]

lcms._cmsStageAllocIdentityCurves.restype = cmsStage
lcms._cmsStageAllocIdentityCurves.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

lcms.cmsStageAllocCLut16bit.restype = cmsStage
lcms.cmsStageAllocCLut16bit.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]

lcms.cmsStageSampleCLut16bit.restype = ctypes.c_int
lcms.cmsStageSampleCLut16bit.argtypes = [cmsStage, SAMPLER_FN, ctypes.c_void_p, ctypes.c_uint32]

lcms.cmsMLUalloc.restype = cmsMLU
lcms.cmsMLUalloc.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
lcms.cmsMLUsetASCII.argtypes = [cmsMLU, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
lcms.cmsMLUfree.argtypes = [cmsMLU]

lcms.cmsWriteTag.argtypes = [cmsHPROFILE, ctypes.c_uint32, ctypes.c_void_p]
lcms.cmsWriteTag.restype = ctypes.c_int
lcms.cmsSaveProfileToFile.argtypes = [cmsHPROFILE, ctypes.c_char_p]
lcms.cmsSaveProfileToFile.restype = ctypes.c_int
lcms.cmsCloseProfile.argtypes = [cmsHPROFILE]

# Format constants
TYPE_Lab_16 = 0x000A001A
TYPE_RGB_16 = 0x0004001A

# Signatures
cmsSigCmykData = 0x434D594B  # 'CMYK'
cmsSigLabData  = 0x4C616220  # 'Lab '
cmsSigOutputClass = 0x70727472 # 'prtr'
cmsSigBToA0Tag = 0x42324130  # 'B2A0' (Perceptual)
cmsSigBToA1Tag = 0x42324131  # 'B2A1' (Relative Colorimetric)
cmsSigBToA2Tag = 0x42324132  # 'B2A2' (Saturation)
cmsSigProfileDescriptionTag = 0x64657363 # 'desc'
cmsSigCopyrightTag = 0x63707274 # 'cprt'

def build_profile(src_icm_path, out_icc_path, grid_points=33):
    print(f"Loading base profile: {src_icm_path}")
    hBase = lcms.cmsOpenProfileFromFile(src_icm_path.encode(), b"r")
    if not hBase:
        raise RuntimeError(f"Cannot open {src_icm_path}")

    hLab = lcms.cmsCreateLab4Profile(None)

    # Create destination profile
    hOut = lcms.cmsCreateProfilePlaceholder(None)
    lcms.cmsSetProfileVersion(hOut, ctypes.c_double(4.3))
    lcms.cmsSetColorSpace(hOut, cmsSigCmykData)
    lcms.cmsSetPCS(hOut, cmsSigLabData)
    lcms.cmsSetDeviceClass(hOut, cmsSigOutputClass)

    # Set metadata tags
    mlu_desc = lcms.cmsMLUalloc(None, 1)
    lcms.cmsMLUsetASCII(mlu_desc, b"en", b"US", b"HP LaserJet Pro CP1025nw CMYK (Calibrated 1-bpp)")
    lcms.cmsWriteTag(hOut, cmsSigProfileDescriptionTag, mlu_desc)
    lcms.cmsMLUfree(mlu_desc)

    mlu_cprt = lcms.cmsMLUalloc(None, 1)
    lcms.cmsMLUsetASCII(mlu_cprt, b"en", b"US", b"Copyright (C) 2026 foo2zjs contributors")
    lcms.cmsWriteTag(hOut, cmsSigCopyrightTag, mlu_cprt)
    lcms.cmsMLUfree(mlu_cprt)

    # Build B2A tags for intents 0 (Perceptual), 1 (Rel Colorimetric), 2 (Saturation)
    intents = [
        (0, cmsSigBToA0Tag, "B2A0 (Perceptual)"),
        (1, cmsSigBToA1Tag, "B2A1 (Relative Colorimetric)"),
        (2, cmsSigBToA2Tag, "B2A2 (Saturation)")
    ]

    for intent_code, tag_sig, desc in intents:
        print(f"Building {desc} with {grid_points}x{grid_points}x{grid_points} CLUT...")
        xform = lcms.cmsCreateTransform(hLab, TYPE_Lab_16, hBase, TYPE_RGB_16, intent_code, 0)
        if not xform:
            raise RuntimeError(f"Failed to create transform for intent {intent_code}")

        out_rgb = (ctypes.c_uint16 * 3)()

        def sampler(in_vals, out_vals, cargo):
            # Transform Lab (16-bit) to Device RGB (16-bit) via base profile
            lcms.cmsDoTransform(xform, in_vals, out_rgb, 1)

            r = out_rgb[0] / 65535.0
            g = out_rgb[1] / 65535.0
            b = out_rgb[2] / 65535.0

            # Convert Device RGB to CMY
            c = 1.0 - r
            m = 1.0 - g
            y = 1.0 - b

            # Smart Clean GCR & 100% Under Color Removal (UCR)
            k_min = min(c, m, y)
            k_start = 0.12 # preserve clean highlights and skin tones without black specks
            if k_min <= k_start:
                K = 0.0
                C = c
                M = m
                Y = y
            else:
                t = (k_min - k_start) / (1.0 - k_start)
                # Smooth GCR fraction ramping from 0.70 in midtones to 1.0 at pure black
                gcr_frac = 0.70 + 0.30 * (t ** 1.5)
                K = min(1.0, max(0.0, k_min * gcr_frac))

                # Clean 100% UCR: subtract exactly the neutral component replaced by K
                C = max(0.0, c - K)
                M = max(0.0, m - K)
                Y = max(0.0, y - K)

            # Clamp and convert to 16-bit
            out_vals[0] = int(round(min(1.0, max(0.0, C)) * 65535.0))
            out_vals[1] = int(round(min(1.0, max(0.0, M)) * 65535.0))
            out_vals[2] = int(round(min(1.0, max(0.0, Y)) * 65535.0))
            out_vals[3] = int(round(min(1.0, max(0.0, K)) * 65535.0))
            return 1

        cb = SAMPLER_FN(sampler)

        pipe = lcms.cmsPipelineAlloc(None, 3, 4)
        b_curves = lcms._cmsStageAllocIdentityCurves(None, 3)
        lcms.cmsPipelineInsertStage(pipe, 1, b_curves)

        clut = lcms.cmsStageAllocCLut16bit(None, grid_points, 3, 4, None)
        lcms.cmsStageSampleCLut16bit(clut, cb, None, 0)
        lcms.cmsPipelineInsertStage(pipe, 1, clut)

        a_curves = lcms._cmsStageAllocIdentityCurves(None, 4)
        lcms.cmsPipelineInsertStage(pipe, 1, a_curves)

        ret = lcms.cmsWriteTag(hOut, tag_sig, pipe)
        if not ret:
            raise RuntimeError(f"Failed to write tag {tag_sig}")

        lcms.cmsDeleteTransform(xform)

    # Save the profile
    print(f"Saving profile to {out_icc_path}...")
    ret = lcms.cmsSaveProfileToFile(hOut, out_icc_path.encode())
    lcms.cmsCloseProfile(hOut)
    lcms.cmsCloseProfile(hBase)
    lcms.cmsCloseProfile(hLab)

    if not ret:
        raise RuntimeError("Failed to save CMYK ICC profile")
    print(f"Successfully generated {out_icc_path} (size: {os.path.getsize(out_icc_path)} bytes)")

if __name__ == "__main__":
    src = "hp-cp1025-rgb-392-bpp1.icm"
    dst = "hp-cp1025-cmyk.icc"
    build_profile(src, dst, grid_points=33)
