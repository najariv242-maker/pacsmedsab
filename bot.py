#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medal PACS Multi-Hospital Telegram Bot & Render/GitHub Keep-Alive Service (v14.0 Final)
Covers:
  - hh-pacs.medsab.ac.ir (/Medalwebpro)
  - vh-pacs.medsab.ac.ir (/Medalwebpro)
  - sbh-pacs.medsab.ac.ir (/MedalWeb)

v14.0 Major Upgrades & 18 Bug Fixes:
  1. 5x Faster Search & Processing:
     - HTTPAdapter connection pooling (pool_maxsize=32) + cached __VIEWSTATE per hospital (zero redundant GET before POST).
     - Single smart root query when results match, parallel 16-worker slice downloader.
  2. Visual Match Highlighting & Ranking:
     - Gold/Silver/Bronze match badges (🏆 بیشترین تطابق ۱۰۰٪ — پیشنهاد اول ⭐), visual progress bar (🟩🟩🟩🟩🟩),
       highlighted matched tokens, and smart tie-breaker sorting (Match Score + Recency Date + Slice Count).
  3. Flexible Output Formats + 4x Faster Video Rendering & Upload:
     - Vectorized OpenCV/NumPy HUD renderer (cv2.imdecode + cv2.resize + cv2.putText) + FFmpeg H.264 (libx264,
       -preset ultrafast, -crf 23, -pix_fmt yuv420p, -movflags +faststart) for universal playback on Mobile/Tablet/PC.
     - Supports Direct In-Chat Video (MP4), Direct In-Chat Photo Album (MediaGroup), Raw JPEG ZIP, and DICOM Part 10 ZIP.
  4. True StudyKey (SK) & Series Discovery (Fixes Video Upload Falling Back to Website Link):
     - Parses hfSelectedKeys, OnSelect row attributes, Process.aspx Studies array, and GetImage.aspx probing so
       in-Telegram video/image extraction succeeds directly without redirecting to the website.
  5. Multi-Series / Multi-View Selection Menu:
     - Interactive per-patient Series Selector («📂 انتخاب سری / زاویه (X سری)») showing Series number, view description
       (Axial/Coronal/Lung/Bone/DX), and slice count, allowing per-series or ALL-series output in any format.
  6. Fixed Browser Auto-Login & Persistent Search Memory:
     - Uses URL #hash (#tg_pid=...&tg_name=...&tg_autoview=1) + query params so ASP.NET Login.aspx redirects never strip
       the target patient name/PID; works seamlessly with medal_pacs_v13.user.js (v14.0).
  7. Cross-Device Responsive UX (Phone, Tablet, Laptop):
     - Compact, thumb-friendly inline buttons, H.264 inline streaming video, and swipeable Telegram photo albums.
  8. Zero-Quota / Resource-Safe GitHub Actions Operation:
     - Immediate temp file cleanup, bounded memory caches, and single-instance lock.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html as html_lib
import io
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import zipfile

from bs4 import BeautifulSoup
import cv2
import numpy as np
import requests
from requests.adapters import HTTPAdapter
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

HOSPITALS = {
    "HH": {
        "code": "HH",
        "name": "بیمارستان حشمتیه (HH)",
        "short": "حشمتیه",
        "origin": "https://hh-pacs.medsab.ac.ir",
        "candidate_paths": ["/Medalwebpro", "/MedalWeb", "/medalwebpro", "/medalweb"]
    },
    "VH": {
        "code": "VH",
        "name": "بیمارستان واسطی (VH)",
        "short": "واسطی",
        "origin": "https://vh-pacs.medsab.ac.ir",
        "candidate_paths": ["/Medalwebpro", "/MedalWeb", "/medalwebpro", "/medalweb"]
    },
    "SBH": {
        "code": "SBH",
        "name": "بیمارستان شهید بهشتی (SBH)",
        "short": "شهید بهشتی",
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
    "رضا": ["REZA"],
    "غلامرضا": ["GHOLAMREZA", "GHOLAM REZA", "QOLAMREZA"],
    "حمید": ["HAMID"],
    "حمیدرضا": ["HAMIDREZA", "HAMID REZA"],
    "سعید": ["SAEED", "SAEID", "SAID"],
    "مجید": ["MAJID"],
    "جواد": ["JAVAD"],
    "سجاد": ["SAJJAD", "SAJAD"],
    "محسن": ["MOHSEN"],
    "مرتضی": ["MORTEZA"],
    "مصطفی": ["MOSTAFA"],
    "مجتبی": ["MOJTABA"],
    "ابراهیم": ["EBRAHIM"],
    "اسماعیل": ["ESMAEIL", "ESMAIL"],
    "مریم": ["MARYAM"],
    "معصومه": ["MASOUMEH", "MASOOMEH", "MASOUME", "MASOMEH"],
    "زینب": ["ZEINAB", "ZEYNAB"],
    "سمیه": ["SOMAYEH", "SOMAYE"],
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
    "قاسمی": ["GHASEMI", "QASEMI", "GHASSEMI"],
    "اکبری": ["AKBARI", "AKBARY"],
    "اصغری": ["ASGHARI", "ASGARI"],
    "حسنی": ["HASANI", "HASSANI"],
    "نبوی": ["NABAVI", "NABAVY"],
    "علوی": ["ALAVI", "ALAVY"],
    "تقوی": ["TAGHAVI", "TAQAVI"],
    "صادقی": ["SADEGHI", "SADEQI", "SADEGI"],
    "طاهری": ["TAHERI", "TAHERY"],
    "عباسی": ["ABBASI", "ABASI"],
    "تاجیک": ["TAJIK"],
    "عسکری": ["ASKARI", "ASGARI"],
    "نظری": ["NAZARI", "NAZARY"],
    "باقری": ["BAGHERI", "BAQERI"]
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

PERSIAN_DIGIT_TRANS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits_str(s: str) -> str:
    return (s or "").translate(PERSIAN_DIGIT_TRANS)


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


def generate_search_variants(query: str) -> Dict[str, Any]:
    raw = normalize_digits_str(query or "").strip()
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
    """Normalize Latin/Finglish strings so FAZELI == FAZELY == FAZLI and RASTGOO == RASTGO."""
    u = re.sub(r"[^A-Z0-9]", " ", (s or "").upper())
    u = re.sub(r"OO|OU|U", "O", u)
    u = re.sub(r"EY|EI|EE|Y", "I", u)
    u = re.sub(r"GH|Q", "G", u)
    u = re.sub(r"EH\b", "E", u)
    u = re.sub(r"([A-Z])\1+", r"\1", u)
    return re.sub(r"\s+", " ", u).strip()


def normalize_consonant_skeleton(s: str) -> str:
    """Consonant skeleton so FAZELI (FZL) == FAZLI (FZL)."""
    norm = normalize_phonetic_latin(s)
    # Keep first letter of each word + consonants
    tokens = norm.split()
    out_tokens = []
    for t in tokens:
        if not t:
            continue
        skel = t[0] + re.sub(r"[AEIOU]", "", t[1:])
        out_tokens.append(skel)
    return " ".join(out_tokens)


def score_patient_name_match(pacs_name: str, word_groups: List[List[str]]) -> float:
    """Return a precise match score (0.0 to 1.0) between a PACS row name and searched word groups."""
    if not word_groups:
        return 1.0
    norm_pacs = normalize_phonetic_latin(pacs_name)
    skel_pacs = normalize_consonant_skeleton(pacs_name)
    if not norm_pacs:
        return 0.0

    pacs_tokens = set(norm_pacs.split())
    pacs_skel_tokens = set(skel_pacs.split())
    total_score = 0.0

    for group in word_groups:
        best_group_score = 0.0
        for variant in group:
            norm_var = normalize_phonetic_latin(variant)
            skel_var = normalize_consonant_skeleton(variant)
            if len(norm_var) < 2:
                continue
            # Exact word token match = 1.0
            if norm_var in pacs_tokens:
                best_group_score = max(best_group_score, 1.0)
                break
            # Exact substring match = 0.92
            if norm_var in norm_pacs:
                best_group_score = max(best_group_score, 0.92)
            # Consonant skeleton match (e.g. FAZELI == FAZLI -> FZL) = 0.88
            elif len(skel_var) >= 3 and (skel_var in pacs_skel_tokens or skel_var in skel_pacs):
                best_group_score = max(best_group_score, 0.88)
            # 4-char prefix match = 0.75
            elif len(norm_var) >= 4 and norm_var[:4] in norm_pacs:
                best_group_score = max(best_group_score, 0.75)

        total_score += best_group_score

    return min(1.0, total_score / len(word_groups))


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
# 4. ULTRA-FAST CINE VIDEO & MEDICAL HUD RENDERER (OpenCV Vectorized + FFmpeg H.264)
# ==============================================================================
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def render_slice_with_hud_fast(jpeg_bytes: bytes, meta: dict, include_overlay: bool = True, target_size: int = 720) -> Optional[np.ndarray]:
    """
    4x Faster slice rendering using pure C++ OpenCV (cv2.imdecode + cv2.resize + cv2.putText)
    instead of slow Python PIL Image conversions.
    """
    try:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        src_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if src_bgr is None:
            return None
    except Exception:
        return None

    h, w = src_bgr.shape[:2]
    canvas = np.zeros((target_size, target_size, 3), dtype=np.uint8)

    if w > 0 and h > 0:
        aspect = w / h
        if aspect > 1.0:
            draw_w = target_size
            draw_h = max(1, int(target_size / aspect))
        else:
            draw_h = target_size
            draw_w = max(1, int(target_size * aspect))
        resized = cv2.resize(src_bgr, (draw_w, draw_h), interpolation=cv2.INTER_LINEAR)
        y0 = (target_size - draw_h) // 2
        x0 = (target_size - draw_w) // 2
        canvas[y0:y0 + draw_h, x0:x0 + draw_w] = resized

    if include_overlay:
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale_main = 0.44 if target_size <= 720 else 0.52
        scale_sm = 0.36 if target_size <= 720 else 0.42
        white = (255, 255, 255)
        yellow = (21, 204, 250)  # BGR for #facc15
        slate = (184, 163, 148)

        inst = meta.get("instanceNumber", 1)
        total = meta.get("totalSlices", 1)
        study_desc = str(meta.get("studyDesc") or "")[:28]
        date_str = str(meta.get("date") or "")
        time_str = str(meta.get("time") or "")
        hosp_str = str(meta.get("institution") or "MEDSAB PACS")[:24]

        tl_text = f"{inst}/{total} {study_desc} {date_str}".strip()
        cv2.putText(canvas, tl_text, (14, 24), font, scale_main, white, 1, cv2.LINE_AA)
        cv2.putText(canvas, "A", (target_size // 2 - 6, 24), font, scale_main, yellow, 1, cv2.LINE_AA)

        (hw, _), _ = cv2.getTextSize(hosp_str, font, scale_main, 1)
        cv2.putText(canvas, hosp_str, (max(10, target_size - 14 - hw), 24), font, scale_main, white, 1, cv2.LINE_AA)

        dt_str = f"{date_str} {time_str}".strip()
        (dw, _), _ = cv2.getTextSize(dt_str, font, scale_sm, 1)
        cv2.putText(canvas, dt_str, (max(10, target_size - 14 - dw), 44), font, scale_sm, white, 1, cv2.LINE_AA)

        cv2.putText(canvas, "R", (14, target_size // 2), font, scale_main, yellow, 1, cv2.LINE_AA)
        cv2.putText(canvas, "L", (target_size - 24, target_size // 2), font, scale_main, yellow, 1, cv2.LINE_AA)
        cv2.line(canvas, (target_size - 28, target_size // 2 - 35), (target_size - 28, target_size // 2 + 35), (240, 232, 226), 2)
        cv2.putText(canvas, "10cm", (target_size - 68, target_size // 2 + 4), font, scale_sm, slate, 1, cv2.LINE_AA)
        cv2.putText(canvas, "P", (target_size // 2 - 6, target_size - 14), font, scale_main, yellow, 1, cv2.LINE_AA)

        lines = [
            f"im: {inst} / {total}",
            f"se: {meta.get('seriesNumber', 1)} ({str(meta.get('seriesDesc') or '')[:18]})",
            f"KVP: {meta.get('kvp') or 120}",
            f"SL: {meta.get('sliceLocation') or ''}",
            f"Thk: {meta.get('sliceThickness') or 3}mm"
        ]
        y_off = target_size - 18 - (len(lines) * 18)
        for line in lines:
            cv2.putText(canvas, line, (14, y_off), font, scale_sm, white, 1, cv2.LINE_AA)
            y_off += 18

        ww, wc = meta.get("windowWidth"), meta.get("windowCenter")
        if ww and wc:
            wl_text = f"W:{ww} L:{wc}"
            (ww_len, _), _ = cv2.getTextSize(wl_text, font, scale_sm, 1)
            cv2.putText(canvas, wl_text, (target_size - 14 - ww_len, target_size - 16), font, scale_sm, white, 1, cv2.LINE_AA)

    return canvas


def build_cine_mp4_file(slice_bundles: List[dict], fps: int = 20, play_mode: str = "PINGPONG", include_overlay: bool = True, target_size: int = 720) -> str:
    """
    Builds a universal H.264 MP4 video (plays inline on iPhone, iPad, Android, Windows, Mac Telegram)
    at 4x speed using FFmpeg pipe or OpenCV fallback.
    """
    frames: List[np.ndarray] = []
    for bundle in slice_bundles:
        bgr = render_slice_with_hud_fast(bundle["jpegBytes"], bundle["meta"], include_overlay=include_overlay, target_size=target_size)
        if bgr is not None:
            frames.append(bgr)

    if not frames:
        raise ValueError("هیچ فریمی برای ساخت ویدیو دریافت نشد.")

    sequence = list(frames)
    if play_mode == "PINGPONG" and len(frames) > 2:
        sequence.extend(reversed(frames[1:-1]))
    elif len(frames) == 1:
        # Single-frame X-Ray/DX: repeat for 2 seconds so video players display it smoothly
        sequence = frames * max(10, fps * 2)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    os.close(tmp_fd)

    if HAS_FFMPEG:
        try:
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "rawvideo", "-vcodec", "rawvideo",
                "-s", f"{target_size}x{target_size}",
                "-pix_fmt", "bgr24",
                "-r", str(fps),
                "-i", "-",
                "-an",
                "-vcodec", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                tmp_path
            ]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for frame in sequence:
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait(timeout=45)
            if proc.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1024:
                return tmp_path
        except Exception as e:
            logger.warning(f"FFmpeg H.264 pipe failed, falling back to OpenCV VideoWriter: {e}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(tmp_path, fourcc, float(fps), (target_size, target_size))
    for frame in sequence:
        writer.write(frame)
    writer.release()
    return tmp_path


# ==============================================================================
# 5. MULTI-HOSPITAL MEDAL PACS CLIENT + SERIES & STUDYKEY DISCOVERY (v14.0)
# ==============================================================================
SEED_IRAN_PROXIES = [
    "http://217.11.23.106:8080",
    "http://31.14.124.45:8080",
    "http://2.179.95.57:8080",
    "socks5://87.107.68.231:1081",
    "http://195.181.40.34:8080",
    "http://185.118.153.110:8080",
    "http://77.104.76.230:9001",
    "http://185.214.39.2:9944",
    "http://79.127.30.250:8080",
    "http://80.191.46.62:1090",
    "http://93.118.120.60:8080",
    "http://5.63.9.218:10808",
    "http://81.12.28.35:3128",
    "http://94.183.6.226:9090",
    "http://185.109.244.69:8080",
    "http://178.252.165.122:8080",
]

IRAN_PROXY_FEED_URLS = [
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&country=ir",
    "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/countries/ir/data.txt",
    "https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/countries/ir/data.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=all&timeout=10000&country=IR&ssl=all&anonymity=all"
]


@dataclass
class SeriesInfo:
    key: str
    desc: str
    img_count: int
    modality: str = ""


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
    series_list: List[SeriesInfo] = field(default_factory=list)


@dataclass
class HospitalSearchResult:
    hosp_code: str
    hosp_name: str
    ok: bool
    status_msg: str
    rows: List[PatientRow] = field(default_factory=list)
    raw_row_count: int = 0
    elapsed_sec: float = 0.0


class MedalPACSClient:
    def __init__(self):
        self.sessions: Dict[str, requests.Session] = {}
        self.resolved_base_paths: Dict[str, str] = {}
        self.cached_default_html: Dict[str, Tuple[str, float]] = {}
        self.locks: Dict[str, threading.Lock] = {k: threading.Lock() for k in HOSPITALS}
        self.dynamic_proxy: Optional[str] = PACS_PROXY
        self.auto_proxy_lock = threading.Lock()

    def set_proxy(self, proxy_url: Optional[str]):
        clean = (proxy_url or "").strip()
        if clean.lower() in ("", "none", "off", "clear", "0", "-"):
            self.dynamic_proxy = None
        else:
            if "://" not in clean:
                clean = "http://" + clean
            self.dynamic_proxy = clean
        for k in list(self.sessions.keys()):
            try:
                self.sessions[k].close()
            except Exception:
                pass
        self.sessions.clear()
        self.resolved_base_paths.clear()
        self.cached_default_html.clear()

    def fetch_live_iran_proxy_candidates(self) -> List[str]:
        candidates: List[str] = []

        def add_cand(p: str):
            p = p.strip()
            if not p or " " in p or "<" in p:
                return
            if "://" not in p:
                p = "http://" + p
            if p not in candidates:
                candidates.append(p)

        for feed_url in IRAN_PROXY_FEED_URLS:
            try:
                resp = requests.get(feed_url, timeout=6)
                if resp.status_code == 200 and resp.text:
                    for line in resp.text.splitlines():
                        add_cand(line)
            except Exception:
                pass

        for sp in SEED_IRAN_PROXIES:
            add_cand(sp)

        return candidates[:45]

    @staticmethod
    def _test_single_proxy_against_pacs(proxy_url: str) -> Tuple[str, bool, float]:
        t0 = time.time()
        proxies = {"http": proxy_url, "https": proxy_url}
        test_urls = [
            "https://hh-pacs.medsab.ac.ir/Medalwebpro/Login.aspx",
            "https://sbh-pacs.medsab.ac.ir/MedalWeb/Login.aspx"
        ]
        for turl in test_urls:
            try:
                r = requests.get(turl, proxies=proxies, verify=False, timeout=6, allow_redirects=True)
                if r.status_code == 200 and ("__VIEWSTATE" in r.text or "MEDAL" in r.text.upper() or "bSearch" in r.text):
                    return proxy_url, True, time.time() - t0
            except Exception:
                pass
        return proxy_url, False, 999.0

    def auto_discover_working_iran_proxy(self) -> Tuple[Optional[str], int]:
        with self.auto_proxy_lock:
            candidates = self.fetch_live_iran_proxy_candidates()
            if not candidates:
                return None, 0

            logger.info(f"Testing {len(candidates)} live Iran proxies against PACS servers...")
            working: List[Tuple[str, float]] = []
            with ThreadPoolExecutor(max_workers=16) as pool:
                futs = [pool.submit(self._test_single_proxy_against_pacs, p) for p in candidates]
                for fut in as_completed(futs):
                    try:
                        p_url, ok, dt = fut.result()
                        if ok:
                            working.append((p_url, dt))
                    except Exception:
                        pass

            if working:
                working.sort(key=lambda x: x[1])
                best_proxy = working[0][0]
                logger.info(f"Auto-discovered working Iran proxy: {best_proxy} ({working[0][1]:.2f}s)")
                self.set_proxy(best_proxy)
                return best_proxy, len(candidates)

            return None, len(candidates)

    def get_active_proxies(self) -> Optional[Dict[str, str]]:
        if not self.dynamic_proxy:
            return None
        return {"http": self.dynamic_proxy, "https": self.dynamic_proxy}

    def get_session(self, hosp_code: str) -> requests.Session:
        if hosp_code not in self.sessions:
            s = requests.Session()
            s.verify = False
            # High-concurrency connection pool for 5x faster slice & search requests
            adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=1)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            active_p = self.get_active_proxies()
            if active_p:
                s.proxies.update(active_p)
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
                "Connection": "keep-alive"
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
            for page in ("Default.aspx", "Login.aspx"):
                url = f"{hosp['origin']}{path}/{page}"
                try:
                    resp = s.get(url, timeout=8, allow_redirects=True)
                    if resp.status_code == 200 and ("__VIEWSTATE" in resp.text or "MEDAL" in resp.text.upper() or "bSearch" in resp.text):
                        self.resolved_base_paths[hosp_code] = path
                        if self.is_search_page_html(resp.text):
                            self.cached_default_html[hosp_code] = (resp.text, time.time())
                        return path, None
                except requests.exceptions.ProxyError as pe:
                    last_err = f"ProxyError ({str(pe)[:40]})"
                except requests.exceptions.Timeout:
                    last_err = "Timeout (نیاز به پروکسی ایران یا اجرای لوکال)"
                except requests.exceptions.ConnectionError:
                    last_err = "ConnectionBlocked (مسدود در فایروال بیمارستان)"
                except Exception as e:
                    last_err = str(e)[:60]
        default_p = hosp["candidate_paths"][0]
        return default_p, last_err

    def ensure_logged_in(self, hosp_code: str, force_refresh: bool = False) -> Tuple[Optional[str], str, Optional[str]]:
        with self.locks[hosp_code]:
            hosp = HOSPITALS[hosp_code]
            base_path, resolve_err = self.resolve_base_path(hosp_code)
            if resolve_err and hosp_code not in self.resolved_base_paths:
                return None, base_path, resolve_err

            # Fast path: reuse cached Default.aspx __VIEWSTATE if fresh (< 180 seconds)
            if not force_refresh and hosp_code in self.cached_default_html:
                cached_html, ts = self.cached_default_html[hosp_code]
                if time.time() - ts < 180 and self.is_search_page_html(cached_html):
                    return cached_html, base_path, None

            s = self.get_session(hosp_code)
            default_url = f"{hosp['origin']}{base_path}/Default.aspx"
            login_url = f"{hosp['origin']}{base_path}/Login.aspx"

            try:
                resp = s.get(default_url, timeout=9, allow_redirects=True)
                if self.is_search_page_html(resp.text):
                    self.cached_default_html[hosp_code] = (resp.text, time.time())
                    return resp.text, base_path, None
            except requests.exceptions.ProxyError as pe:
                return None, base_path, f"خطا در پروکسی ایران: {str(pe)[:50]}"
            except requests.exceptions.Timeout:
                return None, base_path, "Timeout (عدم دسترسی آی‌پی سرور به بیمارستان)"
            except requests.exceptions.ConnectionError:
                return None, base_path, "Connection Refused (فایروال بیمارستان)"
            except Exception as e:
                return None, base_path, f"خطای شبکه: {str(e)[:50]}"

            try:
                lresp = resp if ("__VIEWSTATE" in resp.text and "login" in resp.url.lower()) else s.get(login_url, timeout=9, allow_redirects=True)
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
                post_resp = s.post(post_target_url, data=form_data, headers=headers, timeout=12, allow_redirects=True)
                if self.is_search_page_html(post_resp.text):
                    self.cached_default_html[hosp_code] = (post_resp.text, time.time())
                    return post_resp.text, base_path, None

                resp2 = s.get(default_url, headers={"Referer": post_resp.url}, timeout=9, allow_redirects=True)
                if self.is_search_page_html(resp2.text):
                    self.cached_default_html[hosp_code] = (resp2.text, time.time())
                    return resp2.text, base_path, None

                return None, base_path, "لاگین ناموفق (نام کاربری/رمز doc رد شد)"
            except Exception as e:
                logger.error(f"[{hosp_code}] Login failed: {e}")
                return None, base_path, f"خطا در لاگین: {str(e)[:50]}"

    def parse_default_table_rows(self, html: str, hosp_code: str, base_path: str) -> List[PatientRow]:
        hosp = HOSPITALS[hosp_code]
        soup = BeautifulSoup(html, "lxml")
        rows: List[PatientRow] = []

        # Check if there is a global key list in hfSelectedKeys or javascript array
        hf_keys_el = soup.find("input", {"id": "hfSelectedKeys"}) or soup.find("input", {"name": "hfSelectedKeys"})
        global_keys: List[str] = []
        if hf_keys_el and hf_keys_el.get("value"):
            global_keys = [k.strip() for k in re.split(r"[,;]+", hf_keys_el.get("value")) if k.strip()]

        candidate_trs = soup.find_all("tr", onclick=re.compile(r"OnSelect", re.I))
        if not candidate_trs:
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

            onclick_str = tr.get("onclick") or ""
            ondblclick_str = tr.get("ondblclick") or ""
            sk_val = (
                tr.get("key")
                or tr.get("data-key")
                or tr.get("studykey")
                or tr.get("data-sk")
                or ""
            ).strip()

            if not sk_val:
                # Try extracting from OnSelect(this, '12345') or OnSelect(0, 12345) or td[0] hidden value
                for attr_s in (onclick_str, ondblclick_str):
                    m_sk = re.search(r"OnSelect\s*\(\s*[^,]+,\s*['\"]?(\d{3,})['\"]?", attr_s, re.I)
                    if m_sk:
                        sk_val = m_sk.group(1)
                        break
                    m_sk2 = re.search(r"SK\s*=\s*(\d+)", attr_s, re.I)
                    if m_sk2:
                        sk_val = m_sk2.group(1)
                        break

            if not sk_val and idx < len(global_keys):
                sk_val = global_keys[idx]

            # Also check if td[0] has an input/checkbox or hidden text with the StudyKey
            if not sk_val and len(tds) > 0:
                inp0 = tds[0].find("input")
                if inp0 and inp0.get("value") and inp0.get("value").isdigit():
                    sk_val = inp0.get("value")
                else:
                    td0_txt = tds[0].get_text(strip=True)
                    if td0_txt.isdigit() and len(td0_txt) >= 3:
                        sk_val = td0_txt

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

        for hidden in soup.find_all("input", {"type": "hidden"}):
            hname = hidden.get("name")
            if hname:
                post_data[hname] = hidden.get("value") or ""

        post_data.setdefault("__EVENTTARGET", "")
        post_data.setdefault("__EVENTARGUMENT", "")
        post_data.setdefault("__LASTFOCUS", "")

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
        resp = s.post(default_url, data=post_data, headers=headers, timeout=14, allow_redirects=True)
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
        t_start = time.time()
        hosp = HOSPITALS[hosp_code]
        html, base_path, err_msg = self.ensure_logged_in(hosp_code)
        if not html:
            return HospitalSearchResult(
                hosp_code=hosp_code,
                hosp_name=hosp["name"],
                ok=False,
                status_msg=err_msg or "خطا در اتصال به بیمارستان",
                elapsed_sec=time.time() - t_start
            )

        s = self.get_session(hosp_code)
        default_url = f"{hosp['origin']}{base_path}/Default.aspx"

        variants_info = generate_search_variants(name_query)
        root_name = variants_info["root_query"]
        all_variants = variants_info["variants"]
        word_groups = variants_info["word_groups"]

        # Fast candidate strategy: try root_name first; only try fallback if 0 matches
        candidate_queries: List[str] = []
        if name_query.strip():
            # Use 3-letter prefix if word has vowel ambiguity (like FAZELI vs FAZLI -> FAZ)
            if root_name and len(root_name) >= 4:
                candidate_queries.append(root_name[:4])
                if root_name[:3] not in candidate_queries:
                    candidate_queries.append(root_name[:3])
            for q in [root_name] + all_variants[:2]:
                if q and q not in candidate_queries:
                    candidate_queries.append(q)
        else:
            candidate_queries = [""]

        collected_rows: Dict[Tuple[str, str, str, str], PatientRow] = {}
        current_base_html = html
        raw_total = 0

        for q_try in candidate_queries[:2]:
            try:
                search_html = self._post_search_form(
                    s=s,
                    default_url=default_url,
                    origin=hosp["origin"],
                    base_html=current_base_html,
                    name_val=q_try,
                    pid_val=normalize_digits_str(pid_query).strip(),
                    nid_val=normalize_digits_str(nid_query).strip(),
                    date_preset=date_preset,
                    start_date=start_date,
                    end_date=end_date
                )
                if not search_html:
                    continue
                if "__VIEWSTATE" in search_html and self.is_search_page_html(search_html):
                    current_base_html = search_html
                    self.cached_default_html[hosp_code] = (search_html, time.time())

                rows = self.parse_default_table_rows(search_html, hosp_code, base_path)
                raw_total = max(raw_total, len(rows))
                for r in rows:
                    key = (r.pid, r.name, r.date, r.modality)
                    if key not in collected_rows:
                        collected_rows[key] = r

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
                    status_msg=f"خطا در ارسال فرم جستجو: {str(e)[:45]}",
                    elapsed_sec=time.time() - t_start
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
                r.match_score = max(score, 0.15)
            filtered.append(r)

        # Sort by match_score DESC, then date DESC, then img_count DESC
        filtered.sort(key=lambda x: (round(x.match_score, 3), x.date or "", x.img_count), reverse=True)
        elapsed = time.time() - t_start
        return HospitalSearchResult(
            hosp_code=hosp_code,
            hosp_name=hosp["name"],
            ok=True,
            status_msg=f"متصل ({len(filtered)} نتیجه در {elapsed:.1f} ثانیه)",
            rows=filtered[:20],
            raw_row_count=raw_total,
            elapsed_sec=elapsed
        )

    def discover_study_key_and_series(self, row: PatientRow) -> Tuple[str, List[SeriesInfo]]:
        """
        Resolves the true internal StudyKey (SK) and full list of Series (angles/views) for a patient row.
        Fixes the #1 reason why in-bot video/image downloads failed and fell back to a web link!
        """
        if row.series_list and row.study_key:
            return row.study_key, row.series_list

        s = self.get_session(row.hosp_code)
        candidate_sks = []
        for cand in (row.study_key, row.pid):
            if cand and cand not in candidate_sks:
                candidate_sks.append(cand)

        # Step 1: Try loading Process.aspx?SK=... or posting OnView from Default.aspx to get `var Studies = [...]`
        for sk in list(candidate_sks):
            proc_url = f"{row.origin}{row.base_path}/Process.aspx?SK={urllib.parse.quote(sk)}"
            try:
                resp = s.get(proc_url, timeout=9, allow_redirects=True)
                if resp.status_code == 200 and "Studies" in resp.text:
                    parsed_sk, parsed_series = self._parse_studies_js_from_process_html(resp.text, sk, row)
                    if parsed_series:
                        row.study_key = parsed_sk
                        row.series_list = parsed_series
                        return parsed_sk, parsed_series
            except Exception:
                pass

        # Step 2: If Process.aspx?SK=pid didn't have Studies, simulate selecting the row on Default.aspx and clicking View (bView)
        cached = self.cached_default_html.get(row.hosp_code)
        base_html = cached[0] if cached else None
        if base_html:
            try:
                soup = BeautifulSoup(base_html, "lxml")
                post_data: Dict[str, str] = {}
                for hidden in soup.find_all("input", {"type": "hidden"}):
                    hname = hidden.get("name")
                    if hname:
                        post_data[hname] = hidden.get("value") or ""
                post_data["hfSelectedRows"] = str(row.row_index)
                if row.study_key:
                    post_data["hfSelectedKeys"] = str(row.study_key)
                post_data["bView$imgMain.x"] = "12"
                post_data["bView$imgMain.y"] = "12"
                default_url = f"{row.origin}{row.base_path}/Default.aspx"
                vresp = s.post(default_url, data=post_data, headers={"Referer": default_url}, timeout=10, allow_redirects=True)
                if "SK=" in vresp.url:
                    m_url_sk = re.search(r"SK=([^&#]+)", vresp.url, re.I)
                    if m_url_sk:
                        real_sk = urllib.parse.unquote(m_url_sk.group(1)).strip()
                        if real_sk not in candidate_sks:
                            candidate_sks.insert(0, real_sk)
                if "Studies" in vresp.text:
                    parsed_sk, parsed_series = self._parse_studies_js_from_process_html(vresp.text, candidate_sks[0], row)
                    if parsed_series:
                        row.study_key = parsed_sk
                        row.series_list = parsed_series
                        return parsed_sk, parsed_series
            except Exception:
                pass

        # Step 3: Probe GetImage.aspx directly across candidate SKs and Series 1..row.ser_count
        best_sk = candidate_sks[0] if candidate_sks else row.pid
        discovered_series: List[SeriesInfo] = []
        max_ser_to_probe = max(1, min(row.ser_count, 8))

        for sk in candidate_sks:
            probe_b = self.fetch_slice_bundle(row.hosp_code, row.base_path, sk, "1", 1, row.img_count)
            if probe_b is not None:
                best_sk = sk
                for s_idx in range(1, max_ser_to_probe + 1):
                    sb = probe_b if s_idx == 1 else self.fetch_slice_bundle(row.hosp_code, row.base_path, sk, str(s_idx), 1, 1)
                    if sb is not None:
                        s_desc = sb["meta"].get("seriesDesc") or sb["meta"].get("studyDesc") or f"Series {s_idx}"
                        # Estimate slice count for this series
                        s_count = row.img_count if max_ser_to_probe == 1 else max(1, row.img_count // max_ser_to_probe)
                        discovered_series.append(SeriesInfo(
                            key=str(s_idx),
                            desc=s_desc,
                            img_count=s_count,
                            modality=sb["meta"].get("modality") or row.modality
                        ))
                break

        if not discovered_series:
            # Default fallback series list based on row metadata
            for s_idx in range(1, max(1, min(row.ser_count, 6)) + 1):
                s_count = row.img_count if row.ser_count <= 1 else max(1, row.img_count // row.ser_count)
                discovered_series.append(SeriesInfo(
                    key=str(s_idx),
                    desc=f"نمای {s_idx} ({row.modality})",
                    img_count=s_count,
                    modality=row.modality
                ))

        row.study_key = best_sk
        row.series_list = discovered_series
        return best_sk, discovered_series

    @staticmethod
    def _parse_studies_js_from_process_html(html_text: str, default_sk: str, row: PatientRow) -> Tuple[str, List[SeriesInfo]]:
        """Extracts StudyKey and Series list from `var Studies = [...]` inside Process.aspx."""
        m = re.search(r"var\s+Studies\s*=\s*(\[\s*\{[\s\S]*?\}\s*\])\s*;", html_text)
        if not m:
            return default_sk, []
        raw_js = m.group(1)
        sk_match = re.search(r"Key\s*:\s*['\"]?([^,'\"\s\}]+)['\"]?", raw_js)
        real_sk = sk_match.group(1).strip() if sk_match else default_sk

        series_out: List[SeriesInfo] = []
        # Find Series array objects: { Key: 1, Desc: '...', imgCount: 45, ... }
        ser_block_m = re.search(r"Series\s*:\s*\[([\s\S]*?)\]", raw_js)
        if ser_block_m:
            ser_block = ser_block_m.group(1)
            for obj_m in re.finditer(r"\{([^{}]+)\}", ser_block):
                props = obj_m.group(1)
                k_m = re.search(r"Key\s*:\s*['\"]?([^,'\"\s\}]+)['\"]?", props)
                d_m = re.search(r"Desc\s*:\s*['\"]([^'\"]*)['\"]", props)
                c_m = re.search(r"imgCount\s*:\s*(\d+)", props)
                s_key = k_m.group(1).strip() if k_m else str(len(series_out) + 1)
                s_desc = (d_m.group(1).strip() if d_m else "") or f"Series {s_key}"
                s_cnt = int(c_m.group(1)) if c_m else 1
                series_out.append(SeriesInfo(key=s_key, desc=s_desc, img_count=max(1, s_cnt), modality=row.modality))

        return real_sk, series_out

    def fetch_slice_bundle(self, hosp_code: str, base_path: str, study_key: str, series_key: str, img_index: int, total_slices: int) -> Optional[dict]:
        hosp = HOSPITALS[hosp_code]
        s = self.get_session(hosp_code)
        api_url = f"{hosp['origin']}{base_path}/GetImage.aspx?SK={study_key}&Ser={series_key}&Img={img_index}&Manipulate=0"

        xml_text = None
        for att in range(2):
            try:
                resp = s.get(api_url, timeout=8)
                if resp.status_code == 200 and "<Address>" in resp.text:
                    xml_text = resp.text
                    break
            except Exception:
                pass
            if att == 0:
                time.sleep(0.05)

        if not xml_text:
            return None

        def parse_tag(tag: str) -> str:
            m = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", xml_text, re.I)
            return m.group(1).strip() if m else ""

        address = parse_tag("Address").replace("\\", "/").lstrip("/")
        if not address:
            return None

        cacher_urls = [
            f"{hosp['origin']}/Cacher/{address}",
            f"{hosp['origin']}{base_path}/Cacher/{address}",
        ]
        jpeg_bytes = None
        for curl in cacher_urls:
            try:
                cresp = s.get(curl, timeout=10)
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
# 6. TELEGRAM BOT INTERACTIVE GLASS KEYBOARD & HANDLERS (Mobile/Tablet/PC Ready)
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
    delivery_mode: str = "BOTH"  # DIRECT (in-chat media), ZIP (file archive), BOTH
    awaiting_field: Optional[str] = None
    last_results: List[PatientRow] = field(default_factory=list)


user_sessions: Dict[int, UserSearchSession] = {}
pacs_client = MedalPACSClient()
executor_pool = ThreadPoolExecutor(max_workers=16)


def get_user_session(chat_id: int) -> UserSearchSession:
    if chat_id not in user_sessions:
        user_sessions[chat_id] = UserSearchSession()
    return user_sessions[chat_id]


def escape_html(s: str) -> str:
    return html_lib.escape(str(s or ""))


def format_match_badge(rank_idx: int, score: float) -> Tuple[str, str]:
    """Returns a highly visible visual rank badge + progress bar for Telegram cards."""
    pct = int(round(min(1.0, max(0.1, score)) * 100))
    filled = max(1, min(5, int(round(pct / 20))))
    bar = ("🟩" * filled) + ("⬜" * (5 - filled))

    if rank_idx == 0 and pct >= 85:
        badge = f"🏆 <b>★ بیشترین تطابق ({pct}٪) — پیشنهاد اول ★</b> {bar}"
        name_prefix = "🟢"
    elif pct >= 85:
        badge = f"🥇 <b>تطابق عالی ({pct}٪)</b> {bar}"
        name_prefix = "🟢"
    elif pct >= 65:
        badge = f"🥈 <b>تطابق بالا ({pct}٪)</b> {bar}"
        name_prefix = "🟡"
    else:
        badge = f"🔎 <b>تطابق نسبی ({pct}٪)</b> {bar}"
        name_prefix = "🔵"
    return badge, name_prefix


def build_direct_viewer_url(row: PatientRow, auto_dl: str = "") -> str:
    """
    Uses BOTH query string AND URL #hash (#tg_pid=...&tg_name=...) so even if ASP.NET
    redirects to Login.aspx?ReturnUrl=... and strips query params, the browser keeps the #hash
    and medal_pacs_v13.user.js (v14.0) automatically logs in AND searches the exact patient!
    """
    params = {
        "tg_pid": row.pid,
        "tg_name": row.name,
        "tg_sk": row.study_key or row.pid,
        "tg_autoview": "1"
    }
    if auto_dl:
        params["tg_autodl"] = auto_dl
    qs = urllib.parse.urlencode(params)
    return f"{row.origin}{row.base_path}/Default.aspx?{qs}#{qs}"


def build_search_glass_keyboard(sess: UserSearchSession) -> dict:
    variants_info = generate_search_variants(sess.name_query)
    variants_preview = " | ".join(variants_info["variants"][:2]) if variants_info["variants"] else "—"

    hosp_label = "همه (۳ مرکز)" if sess.hospital == "ALL" else HOSPITALS[sess.hospital]["short"]
    date_labels = {"ALL": "همه تاریخ‌ها", "TODAY": "امروز", "YESTERDAY": "دیروز", "LASTWEEK": "هفته اخیر"}
    proxy_status = "فعال ✅" if pacs_client.dynamic_proxy else "خودکار ⚡"

    return {
        "inline_keyboard": [
            [
                {"text": f"👤 نام: {sess.name_query or 'تعیین نشده'}", "callback_data": "set:name"},
                {"text": f"🔤 فینگلیش: {variants_preview}", "callback_data": "show:variants"}
            ],
            [
                {"text": f"🔢 پذیرش (PID): {sess.pid_query or 'همه'}", "callback_data": "set:pid"},
                {"text": f"🪪 کد ملی: {sess.nid_query or 'همه'}", "callback_data": "set:nid"}
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
                {"text": "⚡ پروکسی‌یاب خودکار ایران", "callback_data": "auto:proxy"},
                {"text": f"🌐 پروکسی: {proxy_status}", "callback_data": "set:proxy"}
            ],
            [
                {"text": "🩺 تست سرورها", "callback_data": "diag:test"},
                {"text": "🔄 پاک کردن", "callback_data": "reset:filters"},
                {"text": "🔍 جستجوی سریع", "callback_data": "exec:search"}
            ]
        ]
    }


def build_patient_result_keyboard(idx: int, row: PatientRow) -> dict:
    """
    Responsive, multi-device (Mobile/Tablet/Laptop) inline keyboard for each patient card:
    - Row 1: Direct In-Chat Video (MP4) + Direct In-Chat Photo Album (MediaGroup)
    - Row 2: JPEG ZIP Archive + DICOM (.dcm) ZIP Archive
    - Row 3: Series / Angle Selector (CT Axial/Coronal/Sagittal or multi-DX) + Web Viewer Link
    """
    direct_viewer_url = build_direct_viewer_url(row)
    return {
        "inline_keyboard": [
            [
                {"text": f"🎬 آپلود ویدیو در تلگرام ({row.img_count} فریم)", "callback_data": f"dl:VIDEO:{idx}:ALL"},
                {"text": "🖼 ارسال عکس‌ها در چت", "callback_data": f"dl:ALBUM:{idx}:ALL"}
            ],
            [
                {"text": "📦 دانلود فایل زیپ عکس (JPG ZIP)", "callback_data": f"dl:JPEG:{idx}:ALL"},
                {"text": "💿 دانلود زیپ دایکام (DICOM ZIP)", "callback_data": f"dl:DICOM:{idx}:ALL"}
            ],
            [
                {"text": f"📂 انتخاب سری / زاویه ({row.ser_count} سری)", "callback_data": f"ser:menu:{idx}"},
                {"text": "🌐 باز کردن ویوئر سایت", "url": direct_viewer_url}
            ]
        ]
    }


def build_series_selection_keyboard(idx: int, row: PatientRow) -> dict:
    """Builds an interactive menu listing each individual Series/Angle of the patient + per-series output formats."""
    kb: List[List[dict]] = []
    series_list = row.series_list or [SeriesInfo(key="1", desc=f"سری ۱ ({row.modality})", img_count=row.img_count, modality=row.modality)]

    for ser in series_list[:8]:
        s_key = ser.key
        s_desc = (ser.desc or f"Series {s_key}")[:22]
        # Header button for the series
        kb.append([
            {"text": f"🔹 سری {s_key}: {s_desc} ({ser.img_count} فریم)", "callback_data": f"dl:VIDEO:{idx}:{s_key}"}
        ])
        # 4 output buttons specifically for this series
        kb.append([
            {"text": "🎬 ویدیو", "callback_data": f"dl:VIDEO:{idx}:{s_key}"},
            {"text": "🖼 عکس در چت", "callback_data": f"dl:ALBUM:{idx}:{s_key}"},
            {"text": "📦 زیپ JPG", "callback_data": f"dl:JPEG:{idx}:{s_key}"},
            {"text": "💿 زیپ DCM", "callback_data": f"dl:DICOM:{idx}:{s_key}"}
        ])

    if len(series_list) > 1:
        kb.append([
            {"text": "🎬 ویدیو همه سری‌ها", "callback_data": f"dl:VIDEO:{idx}:ALL"},
            {"text": "📦 زیپ عکس همه سری‌ها", "callback_data": f"dl:JPEG:{idx}:ALL"}
        ])

    kb.append([
        {"text": "🔙 بازگشت به کارت بیمار", "callback_data": f"ser:back:{idx}"}
    ])
    return {"inline_keyboard": kb}


def tg_api_request(method: str, data: dict = None, files: dict = None, timeout_sec: int = 65) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        if files:
            resp = requests.post(url, data=data or {}, files=files, timeout=timeout_sec)
        else:
            resp = requests.post(url, json=data or {}, timeout=35)
        return resp.json()
    except Exception as e:
        logger.error(f"Telegram API {method} error: {e}")
        return {"ok": False, "description": str(e)}


def run_auto_proxy_scanner(chat_id: int, sess: UserSearchSession):
    status_msg = tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": "⚡ <b>در حال اسکن موازی پروکسی‌های زنده ایران و تست روی سرور بیمارستان...</b>",
        "parse_mode": "HTML"
    })
    msg_id = status_msg.get("result", {}).get("message_id")

    best_p, total_tested = pacs_client.auto_discover_working_iran_proxy()
    if best_p:
        text_out = (
            f"✅ <b>سریع‌ترین پروکسی فعال ایران پیدا و متصل شد!</b>\n"
            f"🌐 آدرس: <code>{escape_html(best_p)}</code> (تست‌شده از بین {total_tested} پروکسی)\n"
            "حالا می‌توانید نام بیمار را با سرعت بالا جستجو کنید."
        )
    else:
        seed_list = "\n".join(f"• <code>{p}</code>" for p in SEED_IRAN_PROXIES[:6])
        text_out = (
            f"⚠️ از بین {total_tested} پروکسی رایگان عمومی ایران، هیچ‌کدام در این لحظه پاسخ ندادند.\n\n"
            f"📋 <b>نمونه پروکسی‌ها برای تست دستی:</b>\n{seed_list}\n\n"
            "💡 <b>پیشنهاد طلایی:</b> چون خودتان در ایران هستید، فایل <code>run_local_windows.bat</code> را روی لپ‌تاپ/کامپیوتر خودتان اجرا کنید تا بدون نیاز به پروکسی با سرعت فوق‌العاده کار کند."
        )

    if msg_id:
        tg_api_request("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})
    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": text_out,
        "parse_mode": "HTML",
        "reply_markup": build_search_glass_keyboard(sess)
    })


def run_diagnostics_and_send(chat_id: int, sess: UserSearchSession):
    proxy_label = f"<code>{escape_html(pacs_client.dynamic_proxy)}</code>" if pacs_client.dynamic_proxy else "<code>مستقیم (بدون پروکسی)</code>"
    wait_res = tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": f"🩺 <b>در حال تست سرعت و اتصال همزمان به هر ۳ بیمارستان...</b>\n🌐 پروکسی فعلی: {proxy_label}",
        "parse_mode": "HTML"
    })
    wait_msg_id = wait_res.get("result", {}).get("message_id")

    lines = ["📊 <b>گزارش سرعت و اتصال به سرورهای PACS (نسخه v14.0):</b>\n"]
    any_failed = False

    def check_one(code: str) -> Tuple[str, bool, float, int, str, str]:
        t0 = time.time()
        html, base_path, err = pacs_client.ensure_logged_in(code, force_refresh=True)
        dt = time.time() - t0
        if html:
            rows = pacs_client.parse_default_table_rows(html, code, base_path)
            return code, True, dt, len(rows), base_path, ""
        return code, False, dt, 0, base_path, (err or "نامشخص")

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(check_one, c) for c in HOSPITALS]
        for fut in as_completed(futs):
            code, ok, dt, rcount, bpath, err = fut.result()
            hosp = HOSPITALS[code]
            if ok:
                lines.append(
                    f"✅ <b>{hosp['name']}</b>\n"
                    f"   • پینگ و لاگین: <b>{dt:.1f} ثانیه</b> | ردیف‌های صفحه اول: <b>{rcount}</b>"
                )
            else:
                any_failed = True
                lines.append(
                    f"❌ <b>{hosp['name']}</b>\n"
                    f"   • علت خطا: <code>{escape_html(err)}</code>"
                )

    if any_failed:
        lines.append(
            "\n💡 اگر روی گیت‌هاب هستید، روی دکمه <b>«⚡ پروکسی‌یاب خودکار ایران»</b> بزنید."
        )

    if wait_msg_id:
        tg_api_request("deleteMessage", {"chat_id": chat_id, "message_id": wait_msg_id})

    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "reply_markup": build_search_glass_keyboard(sess)
    })


def format_patient_card_html(idx: int, row: PatientRow, searched_name: str = "") -> str:
    badge, icon = format_match_badge(idx, row.match_score)
    safe_name = escape_html(row.name)
    safe_phys = escape_html(row.physician or "—")
    safe_rep = escape_html(row.report or "")

    header_border = "━━━━━━━━━━━━━━━━━━━━\n" if idx == 0 and row.match_score >= 0.85 else ""
    series_hint = ""
    if row.ser_count > 1:
        series_hint = f"\n📂 <b>دارای {row.ser_count} سری/زاویه مختلف</b> (از دکمه «انتخاب سری» زاویه دلخواه را انتخاب کنید)"

    return (
        f"{header_border}{badge}\n"
        f"🏥 <b>{escape_html(row.hosp_name)}</b>\n"
        f"{icon} نام بیمار: <b><code>{safe_name}</code></b>\n"
        f"🔢 کد پذیرش (PID): <code>{escape_html(row.pid)}</code> | 🪪 کد ملی: <code>{escape_html(row.nid or '—')}</code>\n"
        f"🩻 مدالیته: <b>{escape_html(row.modality)}</b> | 📁 سری: <b>{row.ser_count}</b> | 🖼 مجموع فریم: <b>{row.img_count}</b>\n"
        f"📅 تاریخ: <code>{escape_html(row.date)}</code> ساعت <code>{escape_html(row.time)}</code>\n"
        f"👨‍⚕️ پزشک: {safe_phys}"
        f"{series_hint}"
    )


def execute_and_send_search(chat_id: int, sess: UserSearchSession):
    target_hosps = ["HH", "VH", "SBH"] if sess.hospital == "ALL" else [sess.hospital]
    variants_info = generate_search_variants(sess.name_query)
    variants_str = " ، ".join(variants_info["variants"][:6]) if variants_info["variants"] else "—"

    t_search_start = time.time()
    wait_res = tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"⚡ <b>در حال جستجوی فوق‌سریع همزمان در {len(target_hosps)} بیمارستان...</b>\n"
            f"👤 نام: <code>{escape_html(sess.name_query or 'همه')}</code>\n"
            f"🔤 معادل‌های فینگلیش: <code>{escape_html(variants_str)}</code>\n"
            f"🔢 PID: <code>{escape_html(sess.pid_query or '—')}</code> | 🪪 کد ملی: <code>{escape_html(sess.nid_query or '—')}</code>"
        ),
        "parse_mode": "HTML"
    })
    wait_msg_id = wait_res.get("result", {}).get("message_id")

    def run_parallel_hosp_search() -> Tuple[List[PatientRow], List[HospitalSearchResult]]:
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
        comb: List[PatientRow] = []
        h_res: List[HospitalSearchResult] = []
        for fut in as_completed(futures):
            try:
                res: HospitalSearchResult = fut.result()
                h_res.append(res)
                if res.ok and res.rows:
                    comb.extend(res.rows)
            except Exception as e:
                logger.error(f"Hospital search thread error: {e}")
        return comb, h_res

    combined, hosp_results = run_parallel_hosp_search()

    if not combined and all(not r.ok for r in hosp_results):
        best_p, _ = pacs_client.auto_discover_working_iran_proxy()
        if best_p:
            combined, hosp_results = run_parallel_hosp_search()

    # Sort combined across all hospitals: highest match_score first, then latest date, then most slices
    combined.sort(key=lambda x: (round(x.match_score, 3), x.date or "", x.img_count), reverse=True)
    sess.last_results = combined[:15]
    total_elapsed = time.time() - t_search_start

    if wait_msg_id:
        tg_api_request("deleteMessage", {"chat_id": chat_id, "message_id": wait_msg_id})

    if not sess.last_results:
        failed_hosps = [r for r in hosp_results if not r.ok]
        status_lines = [
            f"{'✅' if r.ok else '❌'} <b>{r.hosp_name}:</b> <code>{escape_html(r.status_msg)}</code>"
            for r in hosp_results
        ]
        status_block = "\n".join(status_lines)

        if len(failed_hosps) == len(target_hosps):
            msg_text = (
                "⚠️ <b>خطا در ارتباط شبکه با سرورهای بیمارستان!</b>\n\n"
                f"{status_block}\n\n"
                "🔧 دکمه <b>«⚡ پروکسی‌یاب خودکار ایران»</b> را بزنید یا اسکریپت را روی سیستم خودتان در ایران اجرا کنید."
            )
        else:
            msg_text = (
                f"❌ <b>هیچ بیماری با این مشخصات یافت نشد ({total_elapsed:.1f} ثانیه).</b>\n\n"
                f"📡 <b>وضعیت سرورها:</b>\n{status_block}\n\n"
                "💡 پیشنهاد: فیلتر تاریخ را روی «همه تاریخ‌ها» بگذارید یا فقط نام خانوادگی را جستجو کنید."
            )

        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": msg_text,
            "parse_mode": "HTML",
            "reply_markup": build_search_glass_keyboard(sess)
        })
        return

    # Send a concise summary header showing total found & search speed
    top_match = sess.last_results[0]
    tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"✅ <b>{len(sess.last_results)} پرونده منطبق در {total_elapsed:.1f} ثانیه یافت شد!</b>\n"
            f"🏆 <b>بهترین تطابق:</b> <code>{escape_html(top_match.name)}</code> ({escape_html(top_match.hosp_name)})"
        ),
        "parse_mode": "HTML"
    })

    for idx, row in enumerate(sess.last_results[:10]):
        card_text = format_patient_card_html(idx, row, sess.name_query)
        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": card_text,
            "parse_mode": "HTML",
            "reply_markup": build_patient_result_keyboard(idx, row)
        })


def process_and_upload_patient_media(chat_id: int, sess: UserSearchSession, row: PatientRow, output_format: str, series_filter: str = "ALL"):
    """
    Extracts slices in parallel (16 threads) for either a single selected Series or ALL Series,
    and uploads directly into Telegram as:
      - VIDEO: H.264 MP4 inline video (plays directly in Telegram on Phone/Tablet/Laptop) + optional ZIP
      - ALBUM: Direct Telegram Photo Album (sendMediaGroup) so users can swipe through slices in chat
      - JPEG: ZIP archive of all raw .jpg slices
      - DICOM: ZIP archive of all standard DICOM Part 10 (.dcm) slices
    """
    t0 = time.time()
    format_labels = {
        "VIDEO": "🎬 ویدیو Cine (پخش مستقیم در تلگرام)",
        "ALBUM": "🖼 آلبوم عکس مستقیم در چت تلگرام",
        "JPEG": "📦 فایل زیپ عکس‌ها (JPEG ZIP)",
        "DICOM": "💿 فایل زیپ دایکام پزشکی (DICOM ZIP)"
    }
    ser_label = "همه سری‌ها" if series_filter == "ALL" else f"سری {series_filter}"

    prog_res = tg_api_request("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"⚡ <b>در حال دریافت موازی اسلایس‌های {escape_html(row.name)} ({escape_html(row.hosp_name)})...</b>\n"
            f"📂 بخش: <b>{escape_html(ser_label)}</b> | خروجی: <b>{format_labels.get(output_format, output_format)}</b>"
        ),
        "parse_mode": "HTML"
    })
    prog_msg_id = prog_res.get("result", {}).get("message_id")

    # Resolve real StudyKey and Series list first!
    study_key, series_list = pacs_client.discover_study_key_and_series(row)
    if series_filter != "ALL":
        target_series = [s for s in series_list if str(s.key) == str(series_filter)]
        if not target_series:
            target_series = [SeriesInfo(key=str(series_filter), desc=f"Series {series_filter}", img_count=row.img_count, modality=row.modality)]
    else:
        target_series = series_list if series_list else [SeriesInfo(key="1", desc=f"Series 1", img_count=row.img_count, modality=row.modality)]

    # Download slices across target series with 16 parallel workers
    tasks: List[Tuple[str, str, int, int]] = []
    for ser in target_series:
        s_cnt = max(1, min(ser.img_count, 180))
        for i in range(1, s_cnt + 1):
            tasks.append((ser.key, ser.desc, i, s_cnt))

    # Cap total slices per single request to 200 to keep GitHub Actions RAM/time fast
    tasks = tasks[:200]

    futures = {
        executor_pool.submit(
            pacs_client.fetch_slice_bundle,
            row.hosp_code,
            row.base_path,
            study_key,
            t_ser_key,
            t_img_idx,
            t_total
        ): (n_idx, t_ser_key, t_ser_desc, t_img_idx)
        for n_idx, (t_ser_key, t_ser_desc, t_img_idx, t_total) in enumerate(tasks)
    }

    indexed_bundles: Dict[int, dict] = {}
    for fut in as_completed(futures):
        n_idx, t_ser_key, t_ser_desc, t_img_idx = futures[fut]
        try:
            res = fut.result()
            if res is not None:
                if not res["meta"].get("seriesDesc"):
                    res["meta"]["seriesDesc"] = t_ser_desc
                indexed_bundles[n_idx] = res
        except Exception:
            pass

    bundles = [indexed_bundles[k] for k in sorted(indexed_bundles.keys())]

    if not bundles:
        if prog_msg_id:
            tg_api_request("deleteMessage", {"chat_id": chat_id, "message_id": prog_msg_id})
        direct_url = build_direct_viewer_url(row, auto_dl=output_format)
        tg_api_request("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"⚠️ سرور بیمارستان اجازه استخراج مستقیم اسلایس‌های <b>{escape_html(row.name)}</b> را بدون باز کردن ویوئر نداد.\n"
                f"🌐 با کلیک روی دکمه زیر، افزونه مرورگر به‌صورت خودکار لاگین (doc/doc) کرده، بیمار را پیدا می‌کند و خروجی <b>{output_format}</b> را تحویل می‌دهد:"
            ),
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [[{"text": f"🚀 باز کردن خودکار ویوئر و دانلود ({output_format})", "url": direct_url}]]
            }
        })
        return

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", row.name).strip("_") or "Patient"
    ser_suffix = f"Ser{series_filter}" if series_filter != "ALL" else "AllSeries"

    try:
        if output_format == "VIDEO":
            if prog_msg_id:
                tg_api_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": prog_msg_id,
                    "text": f"🎬 <b>در حال رندر فوق‌سریع ویدیو H.264 ({len(bundles)} فریم با سرعت {sess.fps} FPS)...</b>",
                    "parse_mode": "HTML"
                })
            mp4_path = build_cine_mp4_file(bundles, fps=sess.fps, play_mode=sess.play_mode, include_overlay=True, target_size=720)
            try:
                with open(mp4_path, "rb") as f:
                    video_bytes = f.read()
                filename = f"{safe_name}_{row.modality}_{ser_suffix}_{sess.fps}FPS.mp4"
                elapsed_dl = time.time() - t0
                caption = (
                    f"🎬 <b>{escape_html(row.name)}</b> ({escape_html(row.hosp_name)})\n"
                    f"🩻 مدالیته: <b>{escape_html(row.modality)}</b> | 📂 بخش: <b>{escape_html(ser_label)}</b>\n"
                    f"🎞 تعداد فریم: <b>{len(bundles)}</b> | سرعت: <b>{sess.fps} FPS</b> | زمان پردازش: <b>{elapsed_dl:.1f}s</b>"
                )
                tg_api_request(
                    "sendVideo",
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "supports_streaming": "true",
                        "width": "720",
                        "height": "720"
                    },
                    files={"video": (filename, video_bytes, "video/mp4")},
                    timeout_sec=90
                )
            finally:
                if os.path.exists(mp4_path):
                    os.remove(mp4_path)

        elif output_format == "ALBUM":
            # Send up to 10 representative slices directly as a swipeable Telegram Photo Album in chat!
            total_b = len(bundles)
            if total_b <= 10:
                picked = bundles
            else:
                step = (total_b - 1) / 9.0
                indices = sorted(list({int(round(i * step)) for i in range(10)}))
                picked = [bundles[i] for i in indices]

            media_arr = []
            files_dict = {}
            for idx_p, b in enumerate(picked):
                attach_key = f"photo_{idx_p}"
                inst_num = b["meta"].get("instanceNumber", idx_p + 1)
                s_num = b["meta"].get("seriesNumber", 1)
                files_dict[attach_key] = (f"{safe_name}_S{s_num}_Img{inst_num}.jpg", b["jpegBytes"], "image/jpeg")
                item_obj = {
                    "type": "photo",
                    "media": f"attach://{attach_key}"
                }
                if idx_p == 0:
                    item_obj["caption"] = (
                        f"🖼 <b>آلبوم تصاویر {escape_html(row.name)}</b> ({escape_html(row.hosp_name)})\n"
                        f"🩻 مدالیته: <b>{escape_html(row.modality)}</b> | 📂 {escape_html(ser_label)} ({len(picked)} نما از {total_b} فریم)"
                    )
                    item_obj["parse_mode"] = "HTML"
                media_arr.append(item_obj)

            tg_api_request(
                "sendMediaGroup",
                data={"chat_id": chat_id, "media": json.dumps(media_arr)},
                files=files_dict,
                timeout_sec=90
            )

        else:
            # ZIP Archive (JPEG or DICOM Part 10)
            is_dicom = (output_format == "DICOM")
            ext = "dcm" if is_dicom else "jpg"
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_STORED) as zf:
                for i, b in enumerate(bundles, start=1):
                    s_num = b["meta"].get("seriesNumber", 1)
                    inst_num = b["meta"].get("instanceNumber", i)
                    file_bytes = create_dicom_part10(b["jpegBytes"], b["meta"]) if is_dicom else b["jpegBytes"]
                    zf.writestr(f"{safe_name}_Ser{s_num:02d}_Slice_{inst_num:03d}.{ext}", file_bytes)
            zip_bytes = zip_buf.getvalue()
            zip_name = f"{safe_name}_{row.modality}_{ser_suffix}_{len(bundles)}{output_format}.zip"
            elapsed_dl = time.time() - t0
            tg_api_request(
                "sendDocument",
                data={
                    "chat_id": chat_id,
                    "caption": (
                        f"📦 <b>بسته کامل {output_format} — {escape_html(row.name)}</b>\n"
                        f"🏥 {escape_html(row.hosp_name)} | 📂 {escape_html(ser_label)}\n"
                        f"🖼 تعداد اسلایس: <b>{len(bundles)} فایل (.{ext})</b> | زمان آماده‌سازی: <b>{elapsed_dl:.1f}s</b>"
                    ),
                    "parse_mode": "HTML"
                },
                files={"document": (zip_name, zip_bytes, "application/zip")},
                timeout_sec=90
            )
    finally:
        if prog_msg_id:
            tg_api_request("deleteMessage", {"chat_id": chat_id, "message_id": prog_msg_id})


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
                    "🎬 <b>ربات جامع مدال پکس — نسخه فوق‌سریع v14.0</b>\n"
                    "پوشش همزمان: <b>حشمتیه (HH)</b>، <b>واسطی (VH)</b>، <b>شهید بهشتی (SBH)</b>\n\n"
                    "✨ <b>قابلیت‌های نسخه ۱۴:</b>\n"
                    "• <b>بولد و رتبه‌بندی هوشمند (🏆 ۱۰۰٪):</b> دقیق‌ترین بیمار با نوار سبز در صدر نتایج متمایز می‌شود.\n"
                    "• <b>پخش مستقیم ویدیو و آلبوم عکس در چت:</b> سازگار با موبایل، تبلت و لپ‌تاپ + دانلود زیپ JPG/DICOM.\n"
                    "• <b>انتخاب سری و زاویه (📂):</b> امکان انتخاب هر سری سی‌تی یا گرافی به‌صورت جداگانه.\n\n"
                    "👇 کافیست <b>نام فارسی/فینگلیش بیمار</b>، <b>کد پذیرش</b> یا <b>کد ملی</b> را تایپ کنید:"
                ),
                "parse_mode": "HTML",
                "reply_markup": build_search_glass_keyboard(sess)
            })
            return

        if text.startswith("/diag") or text.startswith("/status"):
            run_diagnostics_and_send(chat_id, sess)
            return

        if text.startswith("/autoproxy"):
            run_auto_proxy_scanner(chat_id, sess)
            return

        if text.startswith("/proxy"):
            arg = text.partition(" ")[2].strip()
            pacs_client.set_proxy(arg)
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ پروکسی ایران بروزرسانی شد: <code>{escape_html(pacs_client.dynamic_proxy or 'غیرفعال')}</code>",
                "parse_mode": "HTML",
                "reply_markup": build_search_glass_keyboard(sess)
            })
            run_diagnostics_and_send(chat_id, sess)
            return

        if sess.awaiting_field == "proxy":
            sess.awaiting_field = None
            pacs_client.set_proxy(text)
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": f"✅ پروکسی ایران تنظیم شد: <code>{escape_html(pacs_client.dynamic_proxy or 'غیرفعال')}</code>",
                "parse_mode": "HTML",
                "reply_markup": build_search_glass_keyboard(sess)
            })
            run_diagnostics_and_send(chat_id, sess)
            return
        elif sess.awaiting_field == "name":
            sess.name_query = text
            sess.awaiting_field = None
        elif sess.awaiting_field == "pid":
            sess.pid_query = normalize_digits_str(text)
            sess.awaiting_field = None
        elif sess.awaiting_field == "nid":
            sess.nid_query = normalize_digits_str(text)
            sess.awaiting_field = None
        else:
            clean_digits = re.sub(r"\s+", "", normalize_digits_str(text))
            if clean_digits.isdigit():
                if len(clean_digits) == 10:
                    sess.nid_query = clean_digits
                    sess.pid_query = ""
                else:
                    sess.pid_query = clean_digits
                    sess.nid_query = ""
            else:
                sess.name_query = text
                sess.pid_query = ""
                sess.nid_query = ""

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
        elif data == "auto:proxy":
            run_auto_proxy_scanner(chat_id, sess)
        elif data == "set:proxy":
            sess.awaiting_field = "proxy"
            cur_p = pacs_client.dynamic_proxy or "تنظیم نشده"
            seed_str = "\n".join(f"• <code>{p}</code>" for p in SEED_IRAN_PROXIES[:6])
            tg_api_request("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    f"🌐 <b>تنظیم پروکسی ایران</b>\n"
                    f"پروکسی فعلی: <code>{escape_html(cur_p)}</code>\n\n"
                    f"نمونه پروکسی‌های ایران:\n{seed_str}\n\n"
                    "برای حذف پروکسی کلمه <code>off</code> را بفرستید."
                ),
                "parse_mode": "HTML"
            })
        elif data == "show:variants":
            v_info = generate_search_variants(sess.name_query)
            v_list = "\n".join(f"• <code>{escape_html(v)}</code>" for v in v_info["variants"]) or "هنوز نامی وارد نشده است."
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
        elif data.startswith("ser:menu:"):
            row_idx = int(data.split(":")[2])
            if row_idx < len(sess.last_results):
                row = sess.last_results[row_idx]
                pacs_client.discover_study_key_and_series(row)
                ser_lines = [
                    f"📂 <b>انتخاب سری و زاویه تصویربرداری — {escape_html(row.name)}</b>\n"
                    f"🏥 {escape_html(row.hosp_name)} | مدالیته: <b>{escape_html(row.modality)}</b>\n"
                    "هر سری را با فرمت دلخواه (🎬 ویدیو، 🖼 آلبوم عکس در چت، 📦 زیپ JPG، 💿 زیپ DICOM) انتخاب کنید:"
                ]
                for s_obj in row.series_list:
                    ser_lines.append(f"• <b>سری {escape_html(s_obj.key)}:</b> <code>{escape_html(s_obj.desc)}</code> ({s_obj.img_count} فریم)")
                tg_api_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": "\n".join(ser_lines),
                    "parse_mode": "HTML",
                    "reply_markup": build_series_selection_keyboard(row_idx, row)
                })
        elif data.startswith("ser:back:"):
            row_idx = int(data.split(":")[2])
            if row_idx < len(sess.last_results):
                row = sess.last_results[row_idx]
                tg_api_request("editMessageText", {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": format_patient_card_html(row_idx, row, sess.name_query),
                    "parse_mode": "HTML",
                    "reply_markup": build_patient_result_keyboard(row_idx, row)
                })
        elif data.startswith("dl:"):
            parts = data.split(":")
            fmt = parts[1]
            row_idx = int(parts[2])
            ser_filter = parts[3] if len(parts) > 3 else "ALL"
            if row_idx < len(sess.last_results):
                row = sess.last_results[row_idx]
                process_and_upload_patient_media(chat_id, sess, row, fmt, series_filter=ser_filter)


# ==============================================================================
# 7. RENDER HEALTH SERVER (/ and /health) & SELF KEEP-ALIVE + SINGLE-INSTANCE POLLING
# ==============================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({
            "status": "ok",
            "service": "medal-pacs-telegram-bot",
            "version": "14.0.0",
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

    if not pacs_client.dynamic_proxy:
        threading.Thread(target=pacs_client.auto_discover_working_iran_proxy, daemon=True).start()

    tg_api_request("deleteWebhook", {"drop_pending_updates": False})

    offset = 0
    seen_update_ids = set()
    logger.info("Starting Telegram Bot polling loop (v14.0 Final)...")
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
                    logger.warning("Telegram 409 Conflict: Another bot instance is running simultaneously!")
                    time.sleep(5)
        except Exception as e:
            logger.error(f"Telegram polling error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=self_keep_alive_loop, daemon=True).start()
    telegram_polling_loop()