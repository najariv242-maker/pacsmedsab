#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medal PACS Multi-Hospital Telegram Bot & Render Keep-Alive Service (v13.1)
Covers:
  - hh-pacs.medsab.ac.ir (/Medalwebpro)
  - vh-pacs.medsab.ac.ir (/Medalwebpro)
  - sbh-pacs.medsab.ac.ir (/MedalWeb)
Features:
  1. Smart Persian-to-Finglish Phonetic & Fuzzy Search across all 3 hospitals simultaneously.
  2. Full Glass Inline Keyboard (Name, PID, NID, Modality, Date Preset, Hospital Filter, Video FPS).
  3. Direct Auto-Login Viewer Link (works seamlessly with medal_pacs_v13.user.js).
  4. In-Telegram Extraction & Upload of:
     - Cine Video (.mp4) with exact v12 Medical HUD overlay, Ping-Pong/Forward mode & custom FPS
     - DICOM Part 10 (.dcm) ZIP archive (100% port of v12 createDicomPart10)
     - Raw JPEG (.jpg) ZIP archive for single series or ALL series
  5. Built-in ThreadingHTTPServer (/ and /health) for Render.com + 5-minute Keep-Alive self-ping.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
import re
import struct
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple
import urllib.parse
import zipfile

from bs4 import BeautifulSoup
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("MedalPACSBot")

# ==============================================================================
# 1. CONFIGURATION & HOSPITAL REGISTRY
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PACS_USERNAME = os.environ.get("PACS_USERNAME", "doc").strip()
PACS_PASSWORD = os.environ.get("PACS_PASSWORD", "doc").strip()
PACS_PROXY = os.environ.get("PACS_PROXY", "").strip() or None
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
PORT = int(os.environ.get("PORT", "7860"))

PROXIES = {"http": PACS_PROXY, "https": PACS_PROXY} if PACS_PROXY else None

HOSPITALS = {
    "HH": {
        "code": "HH",
        "name": "بیمارستان حشمتیه (HH)",
        "origin": "https://hh-pacs.medsab.ac.ir",
        "candidate_paths": ["/Medalwebpro", "/MedalWeb", "/medalwebpro", "/medalweb"]
    },
    "VH": {
        "code": "VH",
        "name": "بیمارستان واسطی (VH)",
        "origin": "https://vh-pacs.medsab.ac.ir",
        "candidate_paths": ["/Medalwebpro", "/MedalWeb", "/medalwebpro", "/medalweb"]
    },
    "SBH": {
        "code": "SBH",
        "name": "بیمارستان شهید بهشتی (SBH)",
        "origin": "https://sbh-pacs.medsab.ac.ir",
        "candidate_paths": ["/MedalWeb", "/Medalwebpro", "/medalweb", "/medalwebpro"]
    }
}

# ==============================================================================
# 2. SMART PERSIAN-TO-FINGLISH PHONETIC & FUZZY MATCHING ENGINE
# ==============================================================================
WORD_DICTIONARY: Dict[str, List[str]] = {
    "علی": ["ALI"],
    "علیرضا": ["ALIREZA", "ALI REZA"],
    "محمد": ["MOHAMMAD", "MOHAMAD", "MOHMMAD"],
    "محمدرضا": ["MOHAMMADREZA", "MOHAMADREZA", "MOHAMMAD REZA", "MOHAMAD REZA"],
    "حسین": ["HOSSEIN", "HOSEIN", "HOSIEN", "HOSEYI"],
    "حسن": ["HASAN", "HASSAN"],
    "فاطمه": ["FATEME", "FATEMEH", "FATMA"],
    "زهرا": ["ZAHRA"],
    "مهدی": ["MAHDI", "MEHDI"],
    "مهدیه": ["MAHDIYE", "MAHDIYEH", "MAHDIEH", "MEHDIYEH"],
    "امیر": ["AMIR"],
    "امیرحسین": ["AMIRHOSSEIN", "AMIRHOSEIN", "AMIR HOSSEIN", "AMIR HOSEIN"],
    "امیرمحمد": ["AMIRMOHAMMAD", "AMIR MOHAMMAD", "AMIR MOHAMAD"],
    "ابوالفضل": ["ABOLFAZL", "ABOLFAZEL"],
    "مرضیه": ["MARZIYEH", "MARZIEH", "MARZIYE", "MARZIE"],
    "طاهره": ["TAHERE", "TAHEREH"],
    "طیبه": ["TAYEBE", "TAYEBEH", "TAIEBE"],
    "بهجت": ["BEHJAT"],
    "نرگس": ["NARGES", "NARGESS"],
    "منیره": ["MONIRE", "MONIREH"],
    "ناهید": ["NAHID"],
    "راستگو": ["RASTGOO", "RASTGO", "RASTGOU", "RASTGU", "RAST"],
    "فاضلی": ["FAZELI", "FAZELY", "FAZLI", "FAZEL"],
    "فاضل": ["FAZEL"],
    "راد": ["RAD"],
    "حسینی": ["HOSEINI", "HOSSEINI", "HOSINI", "HOSEYNI"],
    "میرحسینی": ["MIR HOSEINI", "MIRHOSEINI", "MIR HOSSEINI", "MIRHOSSEINI"],
    "میر": ["MIR"],
    "صانع": ["SANE", "SANEE", "SANEI"],
    "سدیدی": ["SADIDI", "SADIDY"],
    "مکارم": ["MAKAREM"],
    "خیرآبادی": ["KHEIRABADI", "KHEYRABADI", "KHIRABADI"],
    "دلاور": ["DELAVAR", "DELAWAR"],
    "دلاوری": ["DELAVARI", "DELAVARY", "DELAVAR"],
    "توفیقیان": ["TOFIGHIAN", "TOFIQIAN", "TOFIGHYAN"],
    "شاهرینی": ["SHAHRAYNI", "SHAHREINI", "SHAHRINI", "SHAHRAINI"],
    "صفری": ["SAFARI", "SAFARY"],
    "دهقان": ["DEHGHAN", "DEHQAN"],
    "دهقانی": ["DEHGHANI", "DEHQANI", "DEHGHANY"],
    "غفوری": ["GHAFORI", "GHAFOURI", "GHAFOORI", "QAFOURI"],
    "چوپان": ["CHOPAN", "CHOOPAN", "CHOUPAN"],
    "شهرآبادی": ["SHAHRABADI", "SHAHR ABADI"],
    "داوچی": ["DAVACHI", "DAVACHY"],
    "برغمدی": ["BARGHAMADI", "BARGHAMADY"],
    "احمدآبادی": ["AHMADABADI", "AHMAD ABADI"],
    "باباکلانی": ["BABAKALANI", "BABA KALANI"],
    "کمایستانی": ["KAMAYESTANI", "KAMAESTANI"],
    "حیدری": ["HEIDARI", "HEYDARI", "HIDARI", "HEIDARY"],
    "مقصودی": ["MAGHSOODI", "MAGHSODI", "MAGHSOUDI", "MAQSOODI"],
    "براتی": ["BARATI", "BARATY"],
    "شاملو": ["SHAMLOO", "SHAMLU", "SHAMLOU", "SHAMLO"],
    "رضایی": ["REZAEI", "REZAI", "REZAEE", "REZAYI"],
    "محمدی": ["MOHAMMADI", "MOHAMADI", "MOHAMMADY"],
    "احمدی": ["AHMADI", "AHMADY"],
    "کریمی": ["KARIMI", "KARIMY"],
    "رحیمی": ["RAHIMI", "RAHIMY"],
    "جعفری": ["JAFARI", "JAFARY", "JAAFARI"],
    "موسوی": ["MOUSAVI", "MOSAVI", "MOOSAVI", "MUSAVI"],
    "هاشمی": ["HASHEMI", "HASHEMY"],
    "قاسمی": ["GHASEMI", "QASEMI", "GHASSEMI"]
}

MORPHEME_PREFIXES = [
    ("راست", ["RAST"]),
    ("تخت", ["TAKHT"]),
    ("بخت", ["BAKHT"]),
    ("سخت", ["SAKHT"]),
    ("دوست", ["DOOST", "DOST", "DOUST"]),
    ("امیر", ["AMIR"]),
    ("محمد", ["MOHAMMAD", "MOHAMAD"]),
    ("علی", ["ALI"]),
    ("حسین", ["HOSSEIN", "HOSEIN"]),
    ("حسن", ["HASAN", "HASSAN"]),
    ("غلام", ["GHOLAM", "QOLAM"]),
    ("عبدال", ["ABDOL"]),
    ("ابوال", ["ABOL"]),
    ("سید", ["SEYED", "SEYYED", "SAIED"]),
    ("میر", ["MIR"]),
    ("شاه", ["SHAH"]),
    ("شهر", ["SHAHR"]),
    ("مهر", ["MEHR"]),
    ("بهار", ["BAHAR"]),
    ("خیر", ["KHEIR", "KHEYR", "KHIR"]),
    ("نور", ["NOOR", "NOUR", "NOR"]),
]

MORPHEME_SUFFIXES = [
    ("آبادی", ["ABADI", "ABADY"]),
    ("ابادی", ["ABADI", "ABADY"]),
    ("آباد", ["ABAD"]),
    ("ستانی", ["ESTANI", "STANI"]),
    ("پور", ["POUR", "POOR", "PUR"]),
    ("نژاد", ["NEZHAD", "NEJAD"]),
    ("زاده", ["ZADEH", "ZADE"]),
    ("منش", ["MANESH"]),
    ("تبار", ["TABAR"]),
    ("وند", ["VAND"]),
    ("نیا", ["NIA", "NIYA"]),
    ("یان", ["IAN", "YAN"]),
    ("فر", ["FAR"]),
    ("لو", ["LOO", "LOU", "LU", "LO"]),
    ("گو", ["GOO", "GO", "GOU", "GU"]),
    ("جو", ["JOO", "JOU", "JO"]),
    ("رو", ["ROO", "RO", "ROU"]),
]

CHAR_MAP = {
    "آ": "A", "ا": "A", "ب": "B", "پ": "P", "ت": "T", "ث": "S",
    "ج": "J", "چ": "CH", "ح": "H", "خ": "KH", "د": "D", "ذ": "Z",
    "ر": "R", "ز": "Z", "ژ": "ZH", "س": "S", "ش": "SH", "ص": "S",
    "ض": "Z", "ط": "T", "ظ": "Z", "ع": "A", "غ": "GH",
    "ف": "F", "ق": "GH", "ک": "K", "ك": "K", "گ": "G", "ل": "L",
    "م": "M", "ن": "N", "و": "O", "ه": "H", "ی": "I", "ي": "I", "ئ": "E"
}


def transliterate_single_persian_word(word: str) -> List[str]:
    clean = word.strip().replace("\u200c", "")
    if not clean:
        return []
    if clean in WORD_DICTIONARY:
        return list(WORD_DICTIONARY[clean])

    prefix_alts = [""]
    suffix_alts = [""]
    core = clean

    for p_str, p_repls in MORPHEME_PREFIXES:
        if core.startswith(p_str) and len(core) > len(p_str):
            prefix_alts = p_repls
            core = core[len(p_str):]
            break

    for s_str, s_repls in MORPHEME_SUFFIXES:
        if core.endswith(s_str) and len(core) >= len(s_str):
            suffix_alts = s_repls
            core = core[:-len(s_str)]
            break

    core_variants: List[str] = []
    if not core:
        core_variants.append("")
    elif core in WORD_DICTIONARY:
        core_variants.extend(WORD_DICTIONARY[core])
    else:
        long_vowels = {"ا", "آ", "و", "ی", "ي"}
        for vowel_mode in (0, 1, 2):
            out = ""
            for i, ch in enumerate(core):
                prev_ch = core[i - 1] if i > 0 else ""
                next_ch = core[i + 1] if i + 1 < len(core) else ""
                is_last = (i == len(core) - 1)

                if i == 0 and ch in ("ا", "آ"):
                    out += "E" if vowel_mode == 1 else "A"
                    continue
                if is_last and ch == "ه":
                    out += "E" if vowel_mode == 0 else "EH"
                    continue
                if is_last and ch in ("ی", "ي"):
                    out += "Y" if vowel_mode == 2 else "I"
                    continue
                if is_last and ch == "و":
                    out += "OO" if vowel_mode == 0 else ("O" if vowel_mode == 1 else "OU")
                    continue
                if ch == "و":
                    out += "V" if i == 0 else ("O" if vowel_mode == 0 else ("OO" if vowel_mode == 1 else "V"))
                    continue
                if ch in ("ی", "ي"):
                    out += "Y" if i == 0 else ("I" if vowel_mode == 0 else ("EI" if vowel_mode == 1 else "EY"))
                    continue
                if ch in ("ق", "غ"):
                    out += "Q" if vowel_mode == 2 else "GH"
                    continue

                out += CHAR_MAP.get(ch, ch)

                is_curr_cons = (ch not in long_vowels and ch != "ه")
                is_next_cons = bool(next_ch and next_ch not in long_vowels)
                prev_was_long = (prev_ch in long_vowels)

                if not is_last and is_curr_cons and is_next_cons:
                    if prev_was_long:
                        continue
                    if i == 0:
                        out += "E" if vowel_mode == 1 else "A"
                    elif vowel_mode == 0:
                        out += "A"
                    elif vowel_mode == 1:
                        out += "E"

            u = out.upper()
            if u not in core_variants:
                core_variants.append(u)

    results: List[str] = []
    for p in prefix_alts:
        for c in core_variants:
            for s in suffix_alts:
                combined = re.sub(r"([A-Z])\1{2,}", r"\1\1", p + c + s)
                if combined and combined not in results:
                    results.append(combined)

    for item in list(results):
        if item.endswith("I"):
            alt = item[:-1] + "Y"
            if alt not in results:
                results.append(alt)
        if item.endswith("E"):
            alt = item + "H"
            if alt not in results:
                results.append(alt)
        if item.endswith("OO"):
            for alt in (item[:-1], item[:-2] + "OU"):
                if alt not in results:
                    results.append(alt)

    if results and len(results[0]) >= 5:
        stem = results[0][:4]
        if stem not in results:
            results.append(stem)

    return results


def generate_search_variants(query: str) -> Dict[str, any]:
    raw = (query or "").strip()
    if not raw:
        return {"primary": "", "root_query": "", "variants": [], "word_groups": []}

    if re.match(r"^[a-zA-Z\s\^\-]+$", raw):
        upper = raw.upper().strip()
        parts = [p for p in re.split(r"[\s\^]+", upper) if p]
        variants: List[str] = [upper]
        if len(parts) >= 2:
            first, last = parts[0], " ".join(parts[1:])
            for cand in (last, f"{last} {first}", f"{last}^{first}"):
                if cand not in variants:
                    variants.append(cand)
            for p in parts:
                if len(p) >= 3 and p not in variants:
                    variants.append(p)
        elif len(parts) == 1 and len(parts[0]) >= 4:
            w = parts[0]
            if w.endswith("I"):
                variants.append(w[:-1] + "Y")
            elif w.endswith("Y"):
                variants.append(w[:-1] + "I")
            if w.endswith("OO"):
                variants.append(w[:-1])
            elif w.endswith("O"):
                variants.append(w + "O")
        root = variants[1] if len(parts) >= 2 else variants[0]
        if len(root) >= 6 and " " not in root and "^" not in root:
            root = root[:5]
        return {"primary": variants[0], "root_query": root, "variants": variants[:14], "word_groups": [[p] for p in parts]}

    words = [w for w in re.split(r"\s+", raw) if w]
    word_groups = [transliterate_single_persian_word(w) for w in words]
    all_variants: List[str] = []

    def add_v(v: str):
        if v and v not in all_variants:
            all_variants.append(v)

    if len(words) == 1:
        for v in word_groups[0]:
            add_v(v)
    else:
        first_vars = word_groups[0]
        second_vars = word_groups[1] if len(word_groups) > 1 else []
        last_vars = word_groups[-1]

        for v in second_vars:
            if len(v) >= 3:
                add_v(v)
        if len(words) > 2:
            if second_vars and last_vars:
                add_v(f"{second_vars[0]} {last_vars[0]}")
                add_v(f"{second_vars[0]}{last_vars[0]}")
            for v in last_vars:
                if len(v) >= 3:
                    add_v(v)

        if len(words) == 2 and second_vars and first_vars:
            add_v(f"{second_vars[0]} {first_vars[0]}")
            add_v(f"{second_vars[0]}^{first_vars[0]}")
        elif len(words) >= 3 and second_vars and last_vars and first_vars:
            add_v(f"{second_vars[0]} {last_vars[0]} {first_vars[0]}")
            add_v(f"{second_vars[0]} {last_vars[0]}^{first_vars[0]}")

        for v in first_vars:
            if len(v) >= 3:
                add_v(v)

    primary = all_variants[0] if all_variants else ""
    root_query = primary
    if root_query and " " not in root_query and "^" not in root_query and len(root_query) >= 6:
        root_query = root_query[:5]

    return {
        "primary": primary,
        "root_query": root_query,
        "variants": all_variants[:14],
        "word_groups": word_groups
    }


def normalize_phonetic_latin(s: str) -> str:
    """Normalize Latin/Finglish strings so FAZELI == FAZELY and RASTGOO == RASTGO."""
    u = re.sub(r"[^A-Z0-9]", " ", (s or "").upper())
    u = re.sub(r"OO|OU|U", "O", u)
    u = re.sub(r"EY|EI|EE|Y", "I", u)
    u = re.sub(r"GH|Q", "G", u)
    u = re.sub(r"EH\b", "E", u)
    u = re.sub(r"([A-Z])\1+", r"\1", u)
    return re.sub(r"\s+", " ", u).strip()


def score_patient_name_match(pacs_name: str, word_groups: List[List[str]]) -> float:
    """Return a match score (0.0 to 1.0) between a PACS row name and our searched word groups."""
    if not word_groups:
        return 1.0
    norm_pacs = normalize_phonetic_latin(pacs_name)
    if not norm_pacs:
        return 0.0

    matched_groups = 0
    for group in word_groups:
        group_hit = False
        for variant in group:
            norm_var = normalize_phonetic_latin(variant)
            if len(norm_var) >= 3 and (norm_var in norm_pacs or norm_var[:4] in norm_pacs):
                group_hit = True
                break
        if group_hit:
            matched_groups += 1

    return matched_groups / len(word_groups)


# ==============================================================================
# 3. DICOM PART 10 (.dcm) GENERATOR (100% Port of v12 createDicomPart10)
# ==============================================================================
def create_dicom_part10(jpeg_bytes: bytes, meta: dict) -> bytes:
    def pad_even(b: bytes, pad_byte: int = 0x20) -> bytes:
        return b + bytes([pad_byte]) if len(b) % 2 != 0 else b

    def str_bytes(s: str, pad_byte: int = 0x20) -> bytes:
        return pad_even((s or "").encode("utf-8"), pad_byte)

    elements: List[Tuple[int, int, str, bytes]] = []

    def add_elem(g: int, e: int, vr: str, val: bytes):
        elements.append((g, e, vr, val))

    def add_string(g: int, e: int, vr: str, s: str):
        add_elem(g, e, vr, str_bytes(s, 0x20))

    def add_us(g: int, e: int, n: int):
        add_elem(g, e, "US", struct.pack("<H", int(n) & 0xFFFF))

    base_uid = "1.2.826.0.1.3680043.9.7133."
    study_uid = meta.get("studyUid") or f"{base_uid}1.{meta.get('studyKey') or '1'}"
    series_uid = meta.get("seriesUid") or f"{study_uid}.{meta.get('seriesKey') or '1'}"
    sop_uid = meta.get("sopUid") or f"{series_uid}.{meta.get('instanceNumber') or '1'}"
    sop_class_uid = "1.2.840.10008.5.1.4.1.1.2"

    date_clean = re.sub(r"\D", "", str(meta.get("date") or ""))[:8]
    time_clean = re.sub(r"\D", "", str(meta.get("time") or ""))[:6]

    add_string(0x0008, 0x0008, "CS", "ORIGINAL\\PRIMARY\\AXIAL")
    add_string(0x0008, 0x0016, "UI", sop_class_uid)
    add_string(0x0008, 0x0018, "UI", sop_uid)
    add_string(0x0008, 0x0020, "DA", date_clean)
    add_string(0x0008, 0x0030, "TM", time_clean)
    add_string(0x0008, 0x0050, "SH", str(meta.get("accessionNumber") or ""))
    add_string(0x0008, 0x0060, "CS", str(meta.get("modality") or "CT"))
    add_string(0x0008, 0x0070, "LO", "Medal PACS")
    add_string(0x0008, 0x0080, "LO", str(meta.get("institution") or "Hospital"))
    add_string(0x0008, 0x1030, "LO", str(meta.get("studyDesc") or ""))
    add_string(0x0008, 0x103E, "LO", str(meta.get("seriesDesc") or ""))

    add_string(0x0010, 0x0010, "PN", str(meta.get("patientName") or "Patient"))
    add_string(0x0010, 0x0020, "LO", str(meta.get("patientID") or ""))
    add_string(0x0010, 0x0040, "CS", str(meta.get("patientSex") or ""))
    add_string(0x0010, 0x1010, "AS", str(meta.get("patientAge") or ""))

    if meta.get("sliceThickness"):
        add_string(0x0018, 0x0050, "DS", str(meta["sliceThickness"]))
    if meta.get("kvp"):
        add_string(0x0018, 0x0060, "DS", str(meta["kvp"]))

    add_string(0x0020, 0x000D, "UI", study_uid)
    add_string(0x0020, 0x000E, "UI", series_uid)
    add_string(0x0020, 0x0011, "IS", str(meta.get("seriesNumber") or meta.get("seriesKey") or 1))
    add_string(0x0020, 0x0013, "IS", str(meta.get("instanceNumber") or 1))

    if meta.get("imagePosition"):
        add_string(0x0020, 0x0032, "DS", str(meta["imagePosition"]))
    if meta.get("imageOrientation"):
        add_string(0x0020, 0x0037, "DS", str(meta["imageOrientation"]))
    if meta.get("sliceLocation"):
        add_string(0x0020, 0x1041, "DS", str(meta["sliceLocation"]))

    add_us(0x0028, 0x0002, 1)
    add_string(0x0028, 0x0004, "CS", "MONOCHROME2")
    add_us(0x0028, 0x0010, int(meta.get("rows") or 512))
    add_us(0x0028, 0x0011, int(meta.get("columns") or 512))
    if meta.get("pixelSpacing"):
        add_string(0x0028, 0x0030, "DS", str(meta["pixelSpacing"]))

    add_us(0x0028, 0x0100, 8)
    add_us(0x0028, 0x0101, 8)
    add_us(0x0028, 0x0102, 7)
    add_us(0x0028, 0x0103, 0)

    if meta.get("windowCenter"):
        add_string(0x0028, 0x1050, "DS", str(meta["windowCenter"]))
    if meta.get("windowWidth"):
        add_string(0x0028, 0x1051, "DS", str(meta["windowWidth"]))
    add_string(0x0028, 0x1052, "DS", "0")
    add_string(0x0028, 0x1053, "DS", "1")

    elements.sort(key=lambda x: (x[0] << 16) | x[1])

    meta_elements: List[Tuple[int, int, str, bytes]] = [
        (0x0002, 0x0001, "OB", bytes([0x00, 0x01])),
        (0x0002, 0x0002, "UI", str_bytes(sop_class_uid, 0x00)),
        (0x0002, 0x0003, "UI", str_bytes(sop_uid, 0x00)),
        (0x0002, 0x0010, "UI", str_bytes("1.2.840.10008.1.2.4.50", 0x00)),
        (0x0002, 0x0012, "UI", str_bytes(base_uid + "99", 0x00)),
    ]

    long_vrs = {"OB", "OW", "OF", "SQ", "UT", "UN"}

    def encode_elem(g: int, e: int, vr: str, val: bytes) -> bytes:
        header = struct.pack("<HH", g, e) + vr.encode("ascii")
        if vr in long_vrs:
            header += struct.pack("<HI", 0, len(val))
        else:
            header += struct.pack("<H", len(val))
        return header + val

    meta_body = b"".join(encode_elem(*el) for el in meta_elements)
    group_0002_len = encode_elem(0x0002, 0x0000, "UL", struct.pack("<I", len(meta_body)))
    body_bytes = b"".join(encode_elem(*el) for el in elements)

    padded_jpeg = jpeg_bytes + (b"\x00" if len(jpeg_bytes) % 2 != 0 else b"")
    pixel_data = (
        struct.pack("<HH", 0x7FE0, 0x0010) + b"OB\x00\x00" + struct.pack("<I", 0xFFFFFFFF) +
        struct.pack("<HHI", 0xFFFE, 0xE000, 0) +
        struct.pack("<HHI", 0xFFFE, 0xE000, len(padded_jpeg)) + padded_jpeg +
        struct.pack("<HHI", 0xFFFE, 0xE0DD, 0)
    )

    return (b"\x00" * 128) + b"DICM" + group_0002_len + meta_body + body_bytes + pixel_data


# ==============================================================================
# 4. CINE VIDEO & MEDICAL HUD RENDERER (100% Port of v12 renderMedicalHUD)
# ==============================================================================
def render_slice_with_hud(jpeg_bytes: bytes, meta: dict, include_overlay: bool = True, target_size: int = 1024) -> Optional[np.ndarray]:
    try:
        src_img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    except Exception:
        return None

    canvas = Image.new("RGB", (target_size, target_size), (0, 0, 0))
    w, h = src_img.size
    if w > 0 and h > 0:
        aspect = w / h
        if aspect > 1.0:
            draw_w = target_size
            draw_h = max(1, int(target_size / aspect))
        else:
            draw_h = target_size
            draw_w = max(1, int(target_size * aspect))
        resized = src_img.resize((draw_w, draw_h), Image.Resampling.BILINEAR)
        canvas.paste(resized, ((target_size - draw_w) // 2, (target_size - draw_h) // 2))

    if include_overlay:
        draw = ImageDraw.Draw(canvas)
        try:
            font_main = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
        except Exception:
            font_main = ImageFont.load_default()
            font_small = font_main

        white = (255, 255, 255)
        yellow = (250, 204, 21)
        slate = (148, 163, 184)

        inst = meta.get("instanceNumber", 1)
        total = meta.get("totalSlices", 1)
        study_desc = meta.get("studyDesc") or ""
        date_str = meta.get("date") or ""
        time_str = meta.get("time") or ""
        hosp_str = meta.get("institution") or "HESHMATIE"

        tl_text = f"{inst} / {total} {study_desc} {date_str}".strip()
        draw.text((16, 16), tl_text, fill=white, font=font_main)
        draw.text((target_size // 2 - 4, 16), "A", fill=yellow, font=font_main)

        hosp_w = draw.textlength(hosp_str, font=font_main)
        dt_str = f"{date_str} {time_str}".strip()
        dt_w = draw.textlength(dt_str, font=font_main)
        draw.text((target_size - 16 - hosp_w, 16), hosp_str, fill=white, font=font_main)
        draw.text((target_size - 16 - dt_w, 36), dt_str, fill=white, font=font_main)

        draw.text((16, target_size // 2 - 7), "R", fill=yellow, font=font_main)
        draw.text((target_size - 24, target_size // 2 - 7), "L", fill=yellow, font=font_main)
        draw.line([(target_size - 28, target_size // 2 - 40), (target_size - 28, target_size // 2 + 40)], fill=(226, 232, 240), width=2)
        draw.text((target_size - 62, target_size // 2 - 6), "10cm", fill=slate, font=font_small)

        draw.text((target_size // 2 - 4, target_size - 30), "P", fill=yellow, font=font_main)

        lines = [
            f"im: {inst} / {total}",
            f"se: {meta.get('seriesNumber', 1)}",
            f"KVP: {meta.get('kvp') or 130}",
            f"SL: {meta.get('sliceLocation') or ''}",
            f"Thickness: {meta.get('sliceThickness') or 3}mm",
            "Zoom: 100%"
        ]
        y_off = target_size - 16 - (len(lines) * 18)
        for line in lines:
            draw.text((16, y_off), line, fill=white, font=font_main)
            y_off += 18

        ww, wc = meta.get("windowWidth"), meta.get("windowCenter")
        if ww and wc:
            wl_text = f"W: {ww} L: {wc}"
            wl_w = draw.textlength(wl_text, font=font_main)
            draw.text((target_size - 16 - wl_w, target_size - 30), wl_text, fill=white, font=font_main)

    rgb_arr = np.array(canvas, dtype=np.uint8)
    return cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)


def build_cine_mp4_file(slice_bundles: List[dict], fps: int = 20, play_mode: str = "PINGPONG", include_overlay: bool = True) -> str:
    frames: List[np.ndarray] = []
    for bundle in slice_bundles:
        bgr = render_slice_with_hud(bundle["jpegBytes"], bundle["meta"], include_overlay=include_overlay, target_size=1024)
        if bgr is not None:
            frames.append(bgr)

    if not frames:
        raise ValueError("هیچ فریمی برای ساخت ویدیو دریافت نشد.")

    sequence = list(frames)
    if play_mode == "PINGPONG" and len(frames) > 2:
        sequence.extend(reversed(frames[1:-1]))

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    os.close(tmp_fd)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_path, fourcc, float(fps), (1024, 1024))
    for frame in sequence:
        writer.write(frame)
    writer.release()
    return tmp_path


# ==============================================================================
# 5. MULTI-HOSPITAL MEDAL PACS CLIENT (Thread-Safe Requests Sessions + Diagnostics)
# ==============================================================================
@dataclass
class PatientRow:
    hosp_code: str
    hosp_name: str
    origin: str
    base_path: str
    row_index: int
    study_key: str
    pid: str
    name: str
    nid: str
    mobile: str
    physician: str
    sex: str
    age: str
    modality: str
    ser_count: int
    img_count: int
    date: str
    time: str
    report: str
    hospital_col: str
    match_score: float = 1.0


@dataclass
class HospitalSearchResult:
    hosp_code: str
    hosp_name: str
    ok: bool
    status_msg: str
    rows: List[PatientRow] = field(default_factory=list)
    raw_row_count: int = 0


class MedalPACSClient:
    def __init__(self):
        self.sessions: Dict[str, requests.Session] = {}
        self.resolved_base_paths: Dict[str, str] = {}
        self.locks: Dict[str, threading.Lock] = {k: threading.Lock() for k in HOSPITALS}

    def get_session(self, hosp_code: str) -> requests.Session:
        if hosp_code not in self.sessions:
            s = requests.Session()
            s.verify = False
            if PROXIES:
                s.proxies.update(PROXIES)
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,fa;q=0.8"
            })
            self.sessions[hosp_code] = s
        return self.sessions[hosp_code]

    @staticmethod
    def is_search_page_html(html: str) -> bool:
        if not html:
            return False
        if "Forgot password?" in html or 'type="password"' in html.lower() or "type='password'" in html.lower():
            return False
        return (
            "bSearch" in html
            or "gMain" in html
            or "OnSelect" in html
            or 'name="ctl09"' in html
            or "bAllDates" in html
            or "hfSelectedKeys" in html
        )

    def resolve_base_path(self, hosp_code: str) -> Tuple[str, Optional[str]]:
        if hosp_code in self.resolved_base_paths:
            return self.resolved_base_paths[hosp_code], None
        hosp = HOSPITALS[hosp_code]
        s = self.get_session(hosp_code)
        last_err = None
        for path in hosp["candidate_paths"]:
            for page in ("Login.aspx", "Default.aspx"):
                url = f"{hosp['origin']}{path}/{page}"
                try:
                    resp = s.get(url, timeout=10, allow_redirects=True)
                    if resp.status_code == 200 and ("__VIEWSTATE" in resp.text or "MEDAL" in resp.text.upper() or "bSearch" in resp.text):
                        self.resolved_base_paths[hosp_code] = path
                        return path, None
                except requests.exceptions.Timeout:
                    last_err = "Timeout (عدم دسترسی سرور ابری به شبکه ایران / نیاز به PACS_PROXY یا اجرای لوکال)"
                except requests.exceptions.ConnectionError as ce:
                    last_err = f"ConnectionError (سرور بیمارستان از اینترنت خارج مسدود است / نیاز به پروکسی ایران)"
                except Exception as e:
                    last_err = str(e)[:80]
        default_p = hosp["candidate_paths"][0]
        return default_p, last_err

    def ensure_logged_in(self, hosp_code: str) -> Tuple[Optional[str], str, Optional[str]]:
        with self.locks[hosp_code]:
            hosp = HOSPITALS[hosp_code]
            base_path, resolve_err = self.resolve_base_path(hosp_code)
            if resolve_err and hosp_code not in self.resolved_base_paths:
                return None, base_path, resolve_err

            s = self.get_session(hosp_code)
            default_url = f"{hosp['origin']}{base_path}/Default.aspx"
            login_url = f"{hosp['origin']}{base_path}/Login.aspx"

            try:
                resp = s.get(default_url, timeout=12, allow_redirects=True)
                if self.is_search_page_html(resp.text):
                    return resp.text, base_path, None
            except requests.exceptions.Timeout:
                return None, base_path, "Timeout (آی‌پی سرور شما به سرور بیمارستان دسترسی ندارد)"
            except requests.exceptions.ConnectionError:
                return None, base_path, "Connection Refused/Blocked (فایروال دانشگاه علوم پزشکی سبزوار آی‌پی خارج را بسته است)"
            except Exception as e:
                logger.warning(f"[{hosp_code}] Initial GET Default.aspx failed: {e}")
                return None, base_path, f"خطای شبکه: {str(e)[:60]}"

            try:
                lresp = resp if ("__VIEWSTATE" in resp.text and "login" in resp.url.lower()) else s.get(login_url, timeout=12, allow_redirects=True)
                soup = BeautifulSoup(lresp.text, "lxml")

                form = soup.find("form")
                post_target_url = login_url
                if form and form.get("action"):
                    post_target_url = urllib.parse.urljoin(lresp.url, form.get("action"))

                form_data: Dict[str, str] = {}
                text_inputs: List[str] = []
                pass_inputs: List[str] = []
                submit_btn_name: Optional[str] = None
                submit_btn_val: str = ""

                for inp in soup.find_all(["input", "button"]):
                    name = inp.get("name")
                    if not name:
                        continue
                    tag_name = inp.name.lower()
                    itype = (inp.get("type") or ("submit" if tag_name == "button" else "text")).lower()
                    val = inp.get("value") or ""

                    if itype == "hidden":
                        form_data[name] = val
                    elif itype == "password":
                        pass_inputs.append(name)
                    elif itype in ("text", ""):
                        text_inputs.append(name)
                    elif itype in ("submit", "button"):
                        low_id = (name + " " + (inp.get("id") or "") + " " + val).lower()
                        if not submit_btn_name or "login" in low_id or "ورود" in low_id:
                            submit_btn_name = name
                            submit_btn_val = val
                    elif itype == "image" and not submit_btn_name:
                        submit_btn_name = f"{name}.x"
                        form_data[f"{name}.x"] = "15"
                        form_data[f"{name}.y"] = "15"

                for tname in text_inputs:
                    if "user" in tname.lower() or "txt" in tname.lower() or "ctl" in tname.lower() or len(text_inputs) == 1:
                        form_data[tname] = PACS_USERNAME
                if text_inputs and not any(k in form_data for k in text_inputs):
                    form_data[text_inputs[0]] = PACS_USERNAME

                for pname in pass_inputs:
                    form_data[pname] = PACS_PASSWORD

                if submit_btn_name and not submit_btn_name.endswith(".x"):
                    form_data[submit_btn_name] = submit_btn_val

                form_data.setdefault("__EVENTTARGET", "")
                form_data.setdefault("__EVENTARGUMENT", "")

                headers = {"Referer": lresp.url, "Origin": hosp["origin"]}
                post_resp = s.post(post_target_url, data=form_data, headers=headers, timeout=15, allow_redirects=True)
                if self.is_search_page_html(post_resp.text):
                    return post_resp.text, base_path, None

                resp2 = s.get(default_url, headers={"Referer": post_resp.url}, timeout=12, allow_redirects=True)
                if self.is_search_page_html(resp2.text):
                    return resp2.text, base_path, None

                return None, base_path, "لاگین ناموفق (صفحه Login رد نشد یا نام کاربری/رمز doc تغییر کرده است)"
            except Exception as e:
                logger.error(f"[{hosp_code}] Login failed: {e}")
                return None, base_path, f"خطا در لاگین: {str(e)[:60]}"

    def parse_default_table_rows(self, html: str, hosp_code: str, base_path: str) -> List[PatientRow]:
        hosp = HOSPITALS[hosp_code]
        soup = BeautifulSoup(html, "lxml")
        rows: List[PatientRow] = []

        # Extract Study Keys (SK) if stored in hfSelectedKeys / table attributes / script arrays
        candidate_trs = soup.find_all("tr", onclick=re.compile(r"OnSelect", re.I))
        if not candidate_trs:
            # Fallback: find rows inside #gMain or any data table with >= 10 columns
            gmain = soup.find(id=re.compile(r"gMain", re.I))
            search_root = gmain if gmain else soup
            for tr in search_root.find_all("tr"):
                if tr.find("th"):
                    continue
                tds = tr.find_all("td")
                if len(tds) >= 11:
                    candidate_trs.append(tr)

        for idx, tr in enumerate(candidate_trs):
            tds = tr.find_all("td")
            if len(tds) < 11:
                continue

            # Extract studyKey from tr attributes or onclick if available
            onclick_str = tr.get("onclick") or ""
            sk_val = tr.get("key") or tr.get("data-key") or ""
            if not sk_val:
                m_sk = re.search(r"OnSelect\s*\(\s*[^,]+,\s*['\"]?(\d+)['\"]?", onclick_str, re.I)
                if m_sk:
                    sk_val = m_sk.group(1)

            pid_txt = tds[1].get_text(strip=True) if len(tds) > 1 else ""
            name_txt = tds[2].get_text(strip=True) if len(tds) > 2 else ""
            if not pid_txt and not name_txt:
                continue

            rows.append(PatientRow(
                hosp_code=hosp_code,
                hosp_name=hosp["name"],
                origin=hosp["origin"],
                base_path=base_path,
                row_index=idx,
                study_key=sk_val or pid_txt,
                pid=pid_txt,
                name=name_txt,
                nid=tds[3].get_text(strip=True) if len(tds) > 3 else "",
                mobile=tds[4].get_text(strip=True) if len(tds) > 4 else "",
                physician=tds[5].get_text(strip=True) if len(tds) > 5 else "",
                sex=tds[6].get_text(strip=True) if len(tds) > 6 else "",
                age=tds[7].get_text(strip=True) if len(tds) > 7 else "",
                modality=tds[8].get_text(strip=True) if len(tds) > 8 else "",
                ser_count=int(re.sub(r"\D", "", tds[9].get_text(strip=True)) or "1") if len(tds) > 9 else 1,
                img_count=int(re.sub(r"\D", "", tds[10].get_text(strip=True)) or "1") if len(tds) > 10 else 1,
                date=tds[11].get_text(strip=True) if len(tds) > 11 else "",
                time=tds[12].get_text(strip=True) if len(tds) > 12 else "",
                report=tds[13].get_text(strip=True) if len(tds) > 13 else "",
                hospital_col=tds[14].get_text(strip=True) if len(tds) > 14 else ""
            ))
        return rows

    def _post_search_form(
        self,
        s: requests.Session,
        default_url: str,
        origin: str,
        base_html: str,
        name_val: str,
        pid_val: str,
        nid_val: str,
        date_preset: str,
        start_date: str,
        end_date: str
    ) -> Optional[str]:
        soup = BeautifulSoup(base_html, "lxml")
        post_data: Dict[str, str] = {}

        # Preserve all hidden fields (__VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION, hfSelectedKeys, etc.)
        for hidden in soup.find_all("input", {"type": "hidden"}):
            hname = hidden.get("name")
            if hname:
                post_data[hname] = hidden.get("value") or ""

        post_data.setdefault("__EVENTTARGET", "")
        post_data.setdefault("__EVENTARGUMENT", "")
        post_data.setdefault("__LASTFOCUS", "")

        # Dynamically verify text input names in case ASP.NET container prefix (e.g. ctl00$ContentPlaceHolder1$ctl09) is present
        ctl_map = {
            "ctl09": name_val,
            "ctl10": nid_val,
            "ctl14": "",
            "ctl15": "",
            "ctl16": pid_val,
            "ctl20": ""
        }
        found_any_ctl = False
        for inp in soup.find_all("input"):
            iname = inp.get("name") or ""
            for short_ctl, val in ctl_map.items():
                if iname == short_ctl or iname.endswith(f"${short_ctl}") or iname.endswith(f"_{short_ctl}"):
                    post_data[iname] = val
                    found_any_ctl = True

        if not found_any_ctl:
            for short_ctl, val in ctl_map.items():
                post_data[short_ctl] = val

        # Preserve select dropdowns if present
        for sel in soup.find_all("select"):
            sname = sel.get("name")
            if sname and sname not in post_data:
                opt = sel.find("option", selected=True)
                if opt and opt.get("value") is not None:
                    post_data[sname] = opt.get("value")

        def resolve_btn_prefix(btn_base: str) -> str:
            for inp in soup.find_all("input", {"type": "image"}):
                iname = inp.get("name") or ""
                if btn_base.lower() in iname.lower():
                    return iname
            return f"{btn_base}$imgMain"

        if start_date and end_date:
            post_data["ctl12$cb"] = "on"
            post_data["ctl12$DT"] = start_date.strip()
            post_data["ctl18$cb"] = "on"
            post_data["ctl18$DT"] = end_date.strip()
            btn_name = resolve_btn_prefix("bSearch")
        elif date_preset == "TODAY":
            btn_name = resolve_btn_prefix("bToday")
        elif date_preset == "YESTERDAY":
            btn_name = resolve_btn_prefix("bYesterday")
        elif date_preset == "LASTWEEK":
            btn_name = resolve_btn_prefix("bLastWeek")
        else:
            # Make sure start/end date checkboxes are NOT checked in post_data so ALL dates are searched
            post_data.pop("ctl12$cb", None)
            post_data.pop("ctl18$cb", None)
            btn_name = resolve_btn_prefix("bAllDates")

        post_data[f"{btn_name}.x"] = "12"
        post_data[f"{btn_name}.y"] = "12"

        headers = {
            "Referer": default_url,
            "Origin": origin,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        resp = s.post(default_url, data=post_data, headers=headers, timeout=18, allow_redirects=True)
        return resp.text

    def search_hospital(
        self,
        hosp_code: str,
        name_query: str = "",
        pid_query: str = "",
        nid_query: str = "",
        modality_filter: str = "ALL",
        date_preset: str = "ALL",
        start_date: str = "",
        end_date: str = ""
    ) -> HospitalSearchResult:
        hosp = HOSPITALS[hosp_code]
        html, base_path, err_msg = self.ensure_logged_in(hosp_code)
        if not html:
            return HospitalSearchResult(
                hosp_code=hosp_code,
                hosp_name=hosp["name"],
                ok=False,
                status_msg=err_msg or "خطا در اتصال یا ورود به بیمارستان"
            )

        s = self.get_session(hosp_code)
        default_url = f"{hosp['origin']}{base_path}/Default.aspx"

        variants_info = generate_search_variants(name_query)
        root_name = variants_info["root_query"]
        all_variants = variants_info["variants"]
        word_groups = variants_info["word_groups"]

        # Build candidate queries to try on PACS if the 5-char root returns 0 rows
        # (e.g. 'FAZEL' misses 'FAZLI', so we also try 'FAZLI' or a 3-letter prefix 'FAZ')
        candidate_queries: List[str] = []
        if name_query.strip():
            for q in [root_name] + all_variants[:3]:
                if q and q not in candidate_queries:
                    candidate_queries.append(q)
            if root_name and len(root_name) >= 4:
                short3 = root_name[:3]
                if short3 not in candidate_queries:
                    candidate_queries.append(short3)
        else:
            candidate_queries = [""]

        collected_rows: Dict[Tuple[str, str, str, str], PatientRow] = {}
        current_base_html = html
        raw_total = 0

        for q_try in candidate_queries[:3]:
            try:
                search_html = self._post_search_form(
                    s=s,
                    default_url=default_url,
                    origin=hosp["origin"],
                    base_html=current_base_html,
                    name_val=q_try,
                    pid_val=pid_query.strip(),
                    nid_val=nid_query.strip(),
                    date_preset=date_preset,
                    start_date=start_date,
                    end_date=end_date
                )
                if not search_html:
                    continue
                if "__VIEWSTATE" in search_html:
                    current_base_html = search_html

                rows = self.parse_default_table_rows(search_html, hosp_code, base_path)
                raw_total = max(raw_total, len(rows))
                for r in rows:
                    key = (r.pid, r.name, r.date, r.modality)
                    if key not in collected_rows:
                        collected_rows[key] = r

                # Filter & check if we already found matching patients
                matched_now = 0
                for r in collected_rows.values():
                    if word_groups:
                        sc = score_patient_name_match(r.name, word_groups)
                        if sc > 0.0 or (q_try and q_try.upper() in r.name.upper()):
                            matched_now += 1
                    else:
                        matched_now += 1

                if matched_now > 0:
                    break
            except Exception as e:
                logger.error(f"[{hosp_code}] Search POST failed for '{q_try}': {e}")
                return HospitalSearchResult(
                    hosp_code=hosp_code,
                    hosp_name=hosp["name"],
                    ok=False,
                    status_msg=f"خطا در ارسال فرم جستجو: {str(e)[:50]}"
                )

        filtered: List[PatientRow] = []
        for r in collected_rows.values():
            if modality_filter and modality_filter != "ALL":
                if r.modality.upper() != modality_filter.upper():
                    continue
            if word_groups:
                score = score_patient_name_match(r.name, word_groups)
                if score <= 0.0 and root_name.upper() not in r.name.upper():
                    continue
                r.match_score = max(score, 0.1)
            filtered.append(r)

        filtered.sort(key=lambda x: x.match_score, reverse=True)
        return HospitalSearchResult(
            hosp_code=hosp_code,
            hosp_name=hosp["name"],
            ok=True,
            status_msg=f"متصل ({len(filtered)} بیمار منطبق از {raw_total} ردیف)",
            rows=filtered[:20],
            raw_row_count=raw_total
        )

    def resolve_study_key_for_row(self, row: PatientRow) -> str:
        """Attempt to discover the true internal StudyKey (SK) if different from PID."""
        if row.study_key and row.study_key != row.pid:
            return row.study_key
        s = self.get_session(row.hosp_code)
        # Test if row.pid works directly with GetImage.aspx
        test_url = f"{row.origin}{row.base_path}/GetImage.aspx?SK={row.pid}&Ser=1&Img=1&Manipulate=0"
        try:
            r = s.get(test_url, timeout=8)
            if r.status_code == 200 and "<Address>" in r.text:
                return row.pid
        except Exception:
            pass
        return row.study_key or row.pid

    def fetch_slice_bundle(self, hosp_code: str, base_path: str, study_key: str, series_key: str, img_index: int, total_slices: int) -> Optional[dict]:
        hosp = HOSPITALS[hosp_code]
        s = self.get_session(hosp_code)
        api_url = f"{hosp['origin']}{base_path}/GetImage.aspx?SK={study_key}&Ser={series_key}&Img={img_index}&Manipulate=0"

        xml_text = None
        for att in range(2):
            try:
                resp = s.get(api_url, timeout=10)
                if resp.status_code == 200 and "<Address>" in resp.text:
                    xml_text = resp.text
                    break
            except Exception:
                pass
            time.sleep(0.1 * (att + 1))

        if not xml_text:
            return None

        def parse_tag(tag: str) -> str:
            m = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", xml_text, re.I)
            return m.group(1).strip() if m else ""

        address = parse_tag("Address")
        if not address:
            return None

        cacher_urls = [
            f"{hosp['origin']}/Cacher/{address}",
            f"{hosp['origin']}{base_path}/Cacher/{address}",
        ]
        jpeg_bytes = None
        for curl in cacher_urls:
            try:
                cresp = s.get(curl, timeout=12)
                if cresp.status_code == 200 and len(cresp.content) > 400:
                    jpeg_bytes = cresp.content
                    break
            except Exception:
                pass

        if not jpeg_bytes:
            return None

        geom = parse_tag("Geometry")
        image_pos, image_orient = "", ""
        if geom and geom != "none":
            parts = geom.split("!")
            if len(parts) >= 3:
                image_pos = "\\".join(v.strip() for v in parts[0].split(","))
                image_orient = "\\".join(v.strip() for v in parts[1].split(",")) + "\\" + "\\".join(v.strip() for v in parts[2].split(","))

        ps_raw = parse_tag("PS")
        meta = {
            "studyKey": study_key,
            "seriesKey": series_key,
            "seriesNumber": int(series_key) if str(series_key).isdigit() else 1,
            "instanceNumber": img_index,
            "totalSlices": total_slices,
            "patientName": parse_tag("PName") or "Patient",
            "patientID": parse_tag("PID") or "",
            "patientSex": parse_tag("PSex"),
            "patientAge": parse_tag("PAge"),
            "modality": parse_tag("Mod") or "CT",
            "date": parse_tag("AcqDate") or parse_tag("Study-Date"),
            "time": parse_tag("AcqTime") or parse_tag("Study-Time"),
            "accessionNumber": parse_tag("AccessionNumber"),
            "studyDesc": parse_tag("StudyDesc"),
            "seriesDesc": parse_tag("SeriesDesc"),
            "institution": parse_tag("Hospital"),
            "rows": int(parse_tag("Height") or "512"),
            "columns": int(parse_tag("Width") or "512"),
            "pixelSpacing": ps_raw.replace(",", "\\") if ps_raw else "",
            "sliceThickness": parse_tag("Slice-Thickness"),
            "sliceLocation": parse_tag("Slice-Location"),
            "kvp": parse_tag("KVP"),
            "imagePosition": image_pos,
            "imageOrientation": image_orient,
            "windowCenter": parse_tag("WC"),
            "windowWidth": parse_tag("WW")
        }
        return {"jpegBytes": jpeg_bytes, "meta": meta}


# ==============================================================================
# 6. TELEGRAM BOT INTERACTIVE GLASS KEYBOARD & HANDLERS
# ==============================================================================
@dataclass
class UserSearchSession:
    name_query: str = ""
    pid_query: str = ""
    nid_query: str = ""
    modality: str = "ALL"
    date_preset: str = "ALL"  # ALL, TODAY, YESTERDAY, LASTWEEK
    hospital: str = "ALL"     # ALL, HH, VH, SBH
    fps: int = 20
    play_mode: str = "PINGPONG"
    awaiting_field: Optional[str] = None
    last_results: List[PatientRow] = field(default_factory=list)


user_sessions: Dict[int, UserSearchSession] = {}
pacs_client = MedalPACSClient()
executor_pool = ThreadPoolExecutor(max_workers=8)


def get_user_session(chat_id: int) -> UserSearchSession:
    if chat_id not in user_sessions:
        user_sessions[chat_id] = UserSearchSession()
    return user_sessions[chat_id]


def build_search_glass_keyboard(sess: UserSearchSession) -> dict:
    variants_info = generate_search_variants(sess.name_query)
    variants_preview = " | ".join(variants_info["variants"][:3]) if variants_info["variants"] else "—"

    hosp_label = "همه (۳ بیمارستان)" if sess.hospital == "ALL" else HOSPITALS[sess.hospital]["name"]
    date_labels = {"ALL": "همه تاریخ‌ها", "TODAY": "امروز", "YESTERDAY": "دیروز", "LASTWEEK": "هفته اخیر"}

    return {
        "inline_keyboard": [
            [
                {"text": f"👤 نام: {sess.name_query or 'تعیین نشده'}", "callback_data": "set:name"},
                {"text": f"🔤 فینگلیش: {variants_preview}", "callback_data": "show:variants"}
            ],
            [
                {"text": f"🔢 کد پذیرش (PID): {sess.pid_query or 'همه'}", "callback_data": "set:pid"},
                {"text": f"🪪 کد ملی (NID): {sess.nid_query or 'همه'}", "callback_data": "set:nid"}
            ],
            [
                {"text": f"🩻 مدالیته: {sess.modality}", "callback_data": "cycle:mod"},
                {"text": f"📅 تاریخ: {date_labels.get(sess.date_preset, 'همه')}", "callback_data": "cycle:date"}
            ],
            [
                {"text": f"🏥 مرکز: {hosp_label}", "callback_data": "cycle:hosp"},
                {"text": f"🎞 سرعت ویدیو: {sess.fps} FPS", "callback_data": "cycle:fps"}
            ],
            [
                {"text": "🩺 تست اتصال سرورها", "callback_data": "diag:test"},
                {"text": "🔄 پاک کردن فیلترها", "callback_data": "reset:filters"},
                {"text": "🔍 اجرای جستجوی جامع", "callback_data": "exec:search"}
            ]
        ]
    }


def build_patient_result_keyboard(idx: int, row: PatientRow) -> dict:
    direct_viewer_url = (
        f"{row.origin}{row.base_path}/Default.aspx"
        f"?tg_pid={urllib.parse.quote(row.pid)}&tg_name={urllib.parse.quote(row.name)}&tg_autoview=1"
    )
    return {
        "inline_keyboard": [
            [
                {"text": "🌐 ورود مستقیم به ویوئر بیمار (اتو-لاگین doc/doc)", "url": direct_viewer_url}
            ],
            [
                {"text": f"🎬 ویدیو Cine ({row.img_count} فریم)", "callback_data": f"dl:VIDEO:{idx}"},
                {"text": "📸 عکس‌ها (JPEG ZIP)", "callback_data": f"dl:JPEG:{idx}"},
                {"text": "💿 دایکام (DICOM ZIP)", "callback_data": f"dl:DICOM:{idx}"}
            ]
        ]
    }


def tg_api_request(method: str, data: dict = None, files: dict = None) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        if files:
            resp = requests.post(url, data=data or {}, files=files, timeout=60)
        else:
            resp = requests.post(url, json=data or {}, timeout=35)
        return resp.json()
    except Exception as e:
        logger.error(f"Telegram API {method} error: {e}")
        return {"ok": False}


def run_diagnostics_and_send(chat_id: int, sess: UserSearchSession):
    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": "🩺 <b>در حال تست اتصال شبکه و لاگین به هر ۳ بیمارستان...</b>",
        "parse_mode": "HTML"
    })
    lines = ["📊 <b>گزارش وضعیت اتصال به سرورهای PACS:</b>\n"]
    any_failed_network = False
    for code, hosp in HOSPITALS.items():
        t0 = time.time()
        html, base_path, err = pacs_client.ensure_logged_in(code)
        dt = time.time() - t0
        if html:
            rows = pacs_client.parse_default_table_rows(html, code, base_path)
            lines.append(
                f"✅ <b>{hosp['name']}</b>\n"
                f"   • مسیر: <code>{hosp['origin']}{base_path}</code>\n"
                f"   • وضعیت: <b>لاگین موفق ({dt:.1f}s)</b> — {len(rows)} ردیف اولیه در صفحه"
            )
        else:
            any_failed_network = True
            lines.append(
                f"❌ <b>{hosp['name']}</b>\n"
                f"   • مسیر: <code>{hosp['origin']}{base_path}</code>\n"
                f"   • علت خطا: <code>{err or 'نامشخص'}</code>"
            )

    if any_failed_network:
        lines.append(
            "\n⚠️ <b>راهنمای رفع خطای شبکه (مهم):</b>\n"
            "سرورهای PACS دانشگاه علوم پزشکی سبزوار (<code>*.medsab.ac.ir</code>) روی اینترنت ملی/داخلی ایران هستند و دسترسی آی‌پی‌های خارج از کشور (مثل سرورهای Render و GitHub Actions) را مسدود می‌کنند.\n"
            "🔹 <b>راه‌حل ۱:</b> یک پروکسی/تانل داخل ایران در متغیر محیطی <code>PACS_PROXY</code> تنظیم کنید.\n"
            "🔹 <b>راه‌حل ۲:</b> فایل <code>bot.py</code> را روی سیستم یا سرور داخل ایران اجرا کنید."
        )

    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "reply_markup": build_search_glass_keyboard(sess)
    })


def execute_and_send_search(chat_id: int, sess: UserSearchSession):
    target_hosps = ["HH", "VH", "SBH"] if sess.hospital == "ALL" else [sess.hospital]
    variants_info = generate_search_variants(sess.name_query)
    variants_str = " ، ".join(variants_info["variants"][:6]) if variants_info["variants"] else "—"

    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"⏳ <b>در حال جستجوی همزمان در {len(target_hosps)} بیمارستان...</b>\n"
            f"👤 نام: <code>{sess.name_query or 'همه'}</code>\n"
            f"🔤 معادل‌های فینگلیش: <code>{variants_str}</code>\n"
            f"🔢 PID: <code>{sess.pid_query or '—'}</code> | 🪪 کد ملی: <code>{sess.nid_query or '—'}</code>"
        ),
        "parse_mode": "HTML"
    })

    futures = [
        executor_pool.submit(
            pacs_client.search_hospital,
            h_code,
            sess.name_query,
            sess.pid_query,
            sess.nid_query,
            sess.modality,
            sess.date_preset
        )
        for h_code in target_hosps
    ]

    combined: List[PatientRow] = []
    hosp_A_results: List[HospitalSearchResult] = []
    for fut in as_completed(futures):
        try:
            res: HospitalSearchResult = fut.result()
            hosp_A_results.append(res)
            if res.ok and res.rows:
                combined.extend(res.rows)
        except Exception as e:
            logger.error(f"Hospital search thread error: {e}")

    combined.sort(key=lambda x: x.match_score, reverse=True)
    sess.last_results = combined[:15]

    if not sess.last_results:
        failed_hosps = [r for r in hosp_A_results if not r.ok]
        status_lines = [
            f"{'✅' if r.ok else '❌'} <b>{r.hosp_name}:</b> <code>{r.status_msg}</code>"
            for r in hosp_A_results
        ]
        status_block = "\n".join(status_lines)

        if len(failed_hosps) == len(target_hosps):
            msg_text = (
                "⚠️ <b>خطا در ارتباط با سرورهای بیمارستان!</b>\n"
                "ربات نتوانست به سرورهای PACS متصل شود یا لاگین کند:\n\n"
                f"{status_block}\n\n"
                "💡 <b>علت اصلی:</b> اگر ربات را روی <b>Render</b> یا <b>GitHub Actions</b> بالا آورده‌اید، آی‌پی این سرورها خارج از ایران است و فایروال دانشگاه علوم پزشکی سبزوار (<code>medsab.ac.ir</code>) اتصال از خارج ایران را مسدود می‌کند.\n"
                "🔧 <b>راه‌حل:</b>\n"
                "۱. ربات را روی کامپیوتر خودتان یا یک سرور/VPS داخل ایران اجرا کنید.\n"
                "۲. یا اگر روی Render/GitHub هستید، متغیر محیطی <code>PACS_PROXY</code> را با آدرس یک پروکسی داخل ایران تنظیم نمایید."
            )
        else:
            msg_text = (
                "❌ <b>هیچ بیماری با این مشخصات در بیمارستان‌های انتخاب‌شده یافت نشد.</b>\n\n"
                f"📡 <b>وضعیت سرورها در این جستجو:</b>\n{status_block}\n\n"
                "می‌توانید فیلتر تاریخ را روی «همه تاریخ‌ها» بگذارید یا بخشی از نام خانوادگی را جستجو کنید."
            )

        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": msg_text,
            "parse_mode": "HTML",
            "reply_markup": build_search_glass_keyboard(sess)
        })
        return

    for idx, row in enumerate(sess.last_results[:10]):
        card_text = (
            f"🏥 <b>{row.hosp_name}</b>\n"
            f"👤 نام بیمار: <code>{row.name}</code>\n"
            f"🔢 کد پذیرش (PID): <code>{row.pid}</code> | 🪪 کد ملی: <code>{row.nid or '—'}</code>\n"
            f"🩻 مدالیته: <b>{row.modality}</b> | 📁 تعداد سری: <b>{row.ser_count}</b> | 🖼 فریم: <b>{row.img_count}</b>\n"
            f"📅 تاریخ: <code>{row.date}</code> ساعت <code>{row.time}</code>\n"
            f"👨‍⚕️ پزشک: {row.physician or '—'}"
        )
        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": card_text,
            "parse_mode": "HTML",
            "reply_markup": build_patient_result_keyboard(idx, row)
        })


def process_and_upload_patient_media(chat_id: int, sess: UserSearchSession, row: PatientRow, output_format: str):
    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"⏳ <b>در حال استخراج اسلایس‌های {row.name} ({row.hosp_name})...</b>\n"
            f"فرمت خروجی: <b>{output_format}</b>"
        ),
        "parse_mode": "HTML"
    })

    study_key = pacs_client.resolve_study_key_for_row(row)
    total_slices = max(1, min(row.img_count, 160))

    futures = {
        executor_pool.submit(pacs_client.fetch_slice_bundle, row.hosp_code, row.base_path, study_key, "1", i, total_slices): i
        for i in range(1, total_slices + 1)
    }
    indexed_bundles: Dict[int, dict] = {}
    for fut in as_completed(futures):
        idx = futures[fut]
        try:
            res = fut.result()
            if res is not None:
                indexed_bundles[idx] = res
        except Exception:
            pass

    bundles = [indexed_bundles[k] for k in sorted(indexed_bundles.keys())]

    if not bundles:
        direct_url = (
            f"{row.origin}{row.base_path}/Default.aspx"
            f"?tg_pid={urllib.parse.quote(row.pid)}&tg_name={urllib.parse.quote(row.name)}&tg_autoview=1&tg_autodl={output_format}"
        )
        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"🌐 لینک مستقیم ویوئر و دانلود خودکار <b>{row.name}</b> آماده است.\n"
                f"با کلیک روی دکمه زیر، افزونه مرورگر به‌صورت خودکار لاگین (doc/doc) کرده و خروجی <b>{output_format}</b> را دانلود می‌کند:"
            ),
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [[{"text": f"🚀 ورود مستقیم و دانلود خودکار ({output_format})", "url": direct_url}]]
            }
        })
        return

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", row.name)
    if output_format == "VIDEO":
        mp4_path = build_cine_mp4_file(bundles, fps=sess.fps, play_mode=sess.play_mode, include_overlay=True)
        try:
            with open(mp4_path, "rb") as f:
                video_bytes = f.read()
            filename = f"{safe_name}_{row.modality}_{sess.fps}FPS.mp4"
            tg_api_request(
                "sendVideo",
                data={"chat_id": chat_id, "caption": f"🎬 {row.name} ({row.modality}) - {sess.fps} FPS"},
                files={"video": (filename, video_bytes, "video/mp4")}
            )
        finally:
            if os.path.exists(mp4_path):
                os.remove(mp4_path)
    else:
        is_dicom = (output_format == "DICOM")
        ext = "dcm" if is_dicom else "jpg"
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_STORED) as zf:
            for i, b in enumerate(bundles, start=1):
                file_bytes = create_dicom_part10(b["jpegBytes"], b["meta"]) if is_dicom else b["jpegBytes"]
                zf.writestr(f"{safe_name}_Slice_{i:03d}.{ext}", file_bytes)
        zip_bytes = zip_buf.getvalue()
        zip_name = f"{safe_name}_{row.modality}_{len(bundles)}{output_format}.zip"
        tg_api_request(
            "sendDocument",
            data={"chat_id": chat_id, "caption": f"📦 {row.name} - {len(bundles)} فایل {output_format}"},
            files={"document": (zip_name, zip_bytes, "application/zip")}
        )


def handle_telegram_update(update: dict):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()
        sess = get_user_session(chat_id)

        if text.startswith("/start") or text.startswith("/search"):
            sess.awaiting_field = None
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "🎬 <b>ربات جامع مدال پکس (حشمتیه، واسطی، شهید بهشتی)</b>\n\n"
                    "می‌توانید مستقیم <b>نام فارسی بیمار</b> (مثلاً <code>علی فاضلی راد</code> یا <code>راستگو</code>) یا <b>کد پذیرش / کد ملی</b> را تایپ کنید، "
                    "یا از <b>منوی شیشه‌ای زیر</b> فیلترها را تنظیم نمایید:\n"
                    "🩺 برای بررسی اتصال سرور به بیمارستان‌ها دستور /diag یا دکمه «تست اتصال سرورها» را بزنید."
                ),
                "parse_mode": "HTML",
                "reply_markup": build_search_glass_keyboard(sess)
            })
            return

        if text.startswith("/diag") or text.startswith("/status"):
            run_diagnostics_and_send(chat_id, sess)
            return

        if sess.awaiting_field == "name":
            sess.name_query = text
            sess.awaiting_field = None
        elif sess.awaiting_field == "pid":
            sess.pid_query = text
            sess.awaiting_field = None
        elif sess.awaiting_field == "nid":
            sess.nid_query = text
            sess.awaiting_field = None
        else:
            clean_digits = re.sub(r"\s+", "", text)
            if clean_digits.isdigit():
                if len(clean_digits) == 10:
                    sess.nid_query = clean_digits
                else:
                    sess.pid_query = clean_digits
            else:
                sess.name_query = text

        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": "✅ فیلترهای جستجو بروزرسانی شد:",
            "reply_markup": build_search_glass_keyboard(sess)
        })
        execute_and_send_search(chat_id, sess)

    elif "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data") or ""
        sess = get_user_session(chat_id)

        tg_api_request("answerCallbackQuery", {"callback_query_id": cb_id})

        if data == "set:name":
            sess.awaiting_field = "name"
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "✍️ لطفاً <b>نام بیمار</b> را به فارسی یا فینگلیش ارسال کنید (مثلاً: <code>علی فاضلی راد</code> یا <code>راستگو</code>):",
                "parse_mode": "HTML"
            })
        elif data == "set:pid":
            sess.awaiting_field = "pid"
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "🔢 لطفاً <b>کد پذیرش (PID)</b> بیمار را ارسال کنید:",
                "parse_mode": "HTML"
            })
        elif data == "set:nid":
            sess.awaiting_field = "nid"
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": "🪪 لطفاً <b>کد ملی (NID)</b> بیمار را ارسال کنید:",
                "parse_mode": "HTML"
            })
        elif data == "show:variants":
            v_info = generate_search_variants(sess.name_query)
            v_list = "\n".join(f"• <code>{v}</code>" for v in v_info["variants"]) or "هنوز نامی وارد نشده است."
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"🔤 <b>حالت‌های فینگلیش تولیدشده برای جستجوی هوشمند:</b>\n\n{v_list}",
                "parse_mode": "HTML"
            })
        elif data == "cycle:mod":
            mods = ["ALL", "CT", "DX", "MR", "US"]
            sess.modality = mods[(mods.index(sess.modality) + 1) % len(mods)]
            tg_api_request("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": msg_id, "reply_markup": build_search_glass_keyboard(sess)
            })
        elif data == "cycle:date":
            dates = ["ALL", "TODAY", "YESTERDAY", "LASTWEEK"]
            sess.date_preset = dates[(dates.index(sess.date_preset) + 1) % len(dates)]
            tg_api_request("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": msg_id, "reply_markup": build_search_glass_keyboard(sess)
            })
        elif data == "cycle:hosp":
            hosps = ["ALL", "HH", "VH", "SBH"]
            sess.hospital = hosps[(hosps.index(sess.hospital) + 1) % len(hosps)]
            tg_api_request("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": msg_id, "reply_markup": build_search_glass_keyboard(sess)
            })
        elif data == "cycle:fps":
            fps_list = [10, 15, 20, 25, 30]
            sess.fps = fps_list[(fps_list.index(sess.fps) + 1) % len(fps_list)] if sess.fps in fps_list else 20
            tg_api_request("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": msg_id, "reply_markup": build_search_glass_keyboard(sess)
            })
        elif data == "reset:filters":
            sess.name_query = ""
            sess.pid_query = ""
            sess.nid_query = ""
            sess.modality = "ALL"
            sess.date_preset = "ALL"
            sess.hospital = "ALL"
            tg_api_request("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": msg_id, "reply_markup": build_search_glass_keyboard(sess)
            })
        elif data == "diag:test":
            run_diagnostics_and_send(chat_id, sess)
        elif data == "exec:search":
            execute_and_send_search(chat_id, sess)
        elif data.startswith("dl:"):
            parts = data.split(":")
            fmt = parts[1]
            row_idx = int(parts[2])
            if row_idx < len(sess.last_results):
                row = sess.last_results[row_idx]
                process_and_upload_patient_media(chat_id, sess, row, fmt)


# ==============================================================================
# 7. RENDER HEALTH SERVER (/ and /health) & SELF KEEP-ALIVE + SINGLE-INSTANCE POLLING
# ==============================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({
            "status": "ok",
            "service": "medal-pacs-telegram-bot",
            "version": "13.2.0",
            "hospitals": list(HOSPITALS.keys()),
            "timestamp": time.time()
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Render Health Web Server listening on 0.0.0.0:{PORT}")
    server.serve_forever()


def self_keep_alive_loop():
    if not RENDER_EXTERNAL_URL:
        return
    ping_url = RENDER_EXTERNAL_URL.rstrip("/") + "/health"
    while True:
        time.sleep(240)
        try:
            resp = requests.get(ping_url, timeout=10)
            logger.info(f"Keep-alive self-ping {ping_url}: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive self-ping warning: {e}")


def telegram_polling_loop():
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN environment variable is not set! Health server is active, waiting for BOT_TOKEN.")
        while True:
            time.sleep(60)

    # Clear any webhook so getUpdates polling works cleanly
    tg_api_request("deleteWebhook", {"drop_pending_updates": False})

    offset = 0
    seen_update_ids = set()
    logger.info("Starting Telegram Bot polling loop...")
    while True:
        try:
            res = tg_api_request("getUpdates", {"offset": offset, "timeout": 25})
            if res.get("ok"):
                for upd in res.get("result", []):
                    uid = upd["update_id"]
                    offset = uid + 1
                    if uid in seen_update_ids:
                        continue
                    seen_update_ids.add(uid)
                    if len(seen_update_ids) > 2000:
                        seen_update_ids.clear()
                    executor_pool.submit(handle_telegram_update, upd)
            else:
                desc = str(res.get("description") or "")
                if "Conflict" in desc or res.get("error_code") == 409:
                    logger.warning("Telegram 409 Conflict detected: Another instance of this bot (e.g. Render + GitHub Actions) is running simultaneously!")
                    time.sleep(5)
        except Exception as e:
            logger.error(f"Telegram polling error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_keep_alive_loop, daemon=True).start()
    telegram_polling_loop()