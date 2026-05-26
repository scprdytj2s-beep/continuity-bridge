#!/usr/bin/env python3
"""Continuity Bridge GUI - LockitNetwork PDF + ALE combiner"""

import sys, re, os, threading, queue as _queue
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("FOUT: pip install pdfplumber"); sys.exit(1)

try:
    import tkinter as tk
    from tkinter import filedialog, ttk
except ImportError:
    print("Tkinter niet gevonden."); sys.exit(1)

# tkinterdnd2 2.x is incompatibel met Python 3.14 (PyEval_RestoreThread-crash
# in AfterProc/PythonCmd via libtkdnd2). Niet importeren zodat libtkdnd2 nooit
# wordt geladen. Drag-and-drop gaat via native ObjC ctypes (zie _setup_native_dnd).
HAS_DND = False

# Native macOS drag-and-drop via PyObjC (fallback wanneer tkinterdnd2 niet werkt)
try:
    import objc as _objc
    from AppKit import NSApplication as _NSApp, NSDragOperationCopy as _DND_COPY
    HAS_NATIVE_DND = True
except ImportError:
    HAS_NATIVE_DND = False


# ---------------------------------------------------------------------------
# PDF PARSER
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path, log):
    clips        = {}
    use_new_fmt  = False   # wordt bijgehouden over pagina's heen
    cur_scene    = ""
    cur_desc     = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue

            # ── Haantjes formaat ──────────────────────────────────────────────
            # Eén pagina per slate; clip-namen: Kaart + CLIP A/B  (bv. "A990C001")
            if "CLIP A" in text and "CLIP B" in text:
                # Kaart (kamerarol A, bv. "A990")
                kaart_m = re.search(r"Kaart\s+([A-Z]\d+)", text)
                if not kaart_m:
                    continue
                kaart_a = kaart_m.group(1)
                kaart_b = "B" + kaart_a[1:]  # "A990" → "B990"

                # Scène (kan leeg zijn)
                scene = ""
                for tbl in page.extract_tables():
                    for row in tbl:
                        if not row: continue
                        for ci, cell in enumerate(row):
                            if cell == "Scène":
                                for nci in range(ci + 1, len(row)):
                                    if row[nci] and row[nci].strip():
                                        scene = row[nci].strip().replace("\n", " ")
                                        break

                # Beschrijving (regel na "Beschrijving", maar geen formulierlabels)
                description = ""
                desc_m = re.search(r"Beschrijving\n(.+)", text)
                if desc_m:
                    desc_raw = desc_m.group(1).strip()
                    if not re.match(r"^(Van:|T/m:|Take|Shot\s|$)", desc_raw):
                        description = desc_raw

                # Algemene Comment onderaan pagina
                comment_m = re.search(r"Comment:\s*(.+)", text)
                general_note = ""
                if comment_m:
                    _gn = comment_m.group(1).strip()
                    # Paginanummer onderaan de pagina niet als comment overnemen
                    if not re.match(r"^\d+$", _gn):
                        general_note = _gn

                # PU-detectie: zoek "PU" kolomkop om x-positie dynamisch te bepalen
                # (hardcoded x≈73 werkt niet voor alle PDFs)
                _pu_col_x = None
                _pu_col_bottom = 370
                _all_words = page.extract_words(x_tolerance=3, y_tolerance=3)
                for _w in _all_words:
                    if _w['text'] == 'PU' and 300 < _w['top'] < 450:
                        _pu_col_x = (_w['x0'] + _w['x1']) / 2
                        _pu_col_bottom = _w.get('bottom', _w['top'] + 10)
                        break

                # Take-nummers → y-coördinaat (linkerkant van tabel, vóór PU-kolom)
                _take_ys = {}
                for _w in _all_words:
                    if _w['top'] > _pu_col_bottom and re.match(r'^\d+$', _w['text']):
                        _w_cx = (_w['x0'] + _w['x1']) / 2
                        if _pu_col_x is None or _w_cx < _pu_col_x - 10:
                            _take_ys[_w['text']] = _w['top']

                # PU-detectie via pixels (image-namen zijn onbetrouwbaar over PDF-versies)
                # Render de PU-kolom als grijswaarden-strip; tel donkere pixels per rij.
                _pu_col_pil = None
                _pu_col_pil_y0 = _pu_col_bottom
                _PU_RES = 150
                _PU_SCALE = _PU_RES / 72.0   # ≈ 2.08 px per punt

                if _pu_col_x is not None and _take_ys:
                    try:
                        _strip_x0 = max(0.0, _pu_col_x - 12.0)
                        _strip_x1 = min(float(page.width), _pu_col_x + 12.0)
                        _strip_y0 = _pu_col_bottom
                        _strip_y1 = float(page.height) - 5.0
                        _col = page.crop((_strip_x0, _strip_y0, _strip_x1, _strip_y1))
                        _pu_col_pil = _col.to_image(resolution=_PU_RES).original.convert('L')
                        _pu_col_pil_y0 = _strip_y0
                    except Exception:
                        _pu_col_pil = None

                def _is_pu(take_num_str):
                    if _pu_col_pil is None or take_num_str not in _take_ys:
                        return False
                    ty = _take_ys[take_num_str]
                    iw, ih = _pu_col_pil.size
                    # Zet PDF-punt-y om naar pixel-y in de gesneden strip
                    cy = int((ty - _pu_col_pil_y0) * _PU_SCALE)
                    # Sla randborden over (≈ 2 pt), kijk 12 pt naar beneden
                    brd = max(1, round(2 * _PU_SCALE))
                    px0 = brd
                    px1 = max(px0 + 1, iw - brd)
                    py0 = max(0, cy + brd)
                    py1 = min(ih, cy + round(12 * _PU_SCALE) - brd)
                    if py0 >= py1 or px0 >= px1:
                        return False
                    # Tel donkere pixels (< 80) — een vinkje heeft er ≥ 6
                    dark = sum(
                        1 for py in range(py0, py1)
                        for px in range(px0, px1)
                        if _pu_col_pil.getpixel((px, py)) < 80
                    )
                    return dark >= 6

                # Take-tabel via extract_tables()
                for tbl in page.extract_tables():
                    header_row_idx = None
                    for ri, row in enumerate(tbl):
                        if row and row[0] and row[0].strip() == "Take":
                            header_row_idx = ri
                            break
                    if header_row_idx is None:
                        continue

                    header = tbl[header_row_idx]
                    clip_a_idx  = next((i for i, c in enumerate(header) if c and "CLIP A" in c), None)
                    clip_b_idx  = next((i for i, c in enumerate(header) if c and "CLIP B" in c), None)
                    notes_idx   = next((i for i, c in enumerate(header) if c and "Notes" in c), None)
                    lengte_idx  = next((i for i, c in enumerate(header) if c and "Lengte" in c), None)
                    if clip_a_idx is None:
                        continue

                    # Notes-stop: nooit verder dan de Lengte-kolom
                    notes_stop = lengte_idx if (lengte_idx is not None
                                                and notes_idx is not None
                                                and lengte_idx > notes_idx) else None

                    pending_clip_a = pending_clip_b = pending_notes = None

                    for row in tbl[header_row_idx + 1:]:
                        if not row: continue

                        # Eerste cel kan leeg zijn bij vervolgrij (multiline cel)
                        raw0 = str(row[0] or "").strip()
                        take_num = raw0.split("\n")[0].strip()
                        is_take_row = bool(re.match(r"^\d+$", take_num))

                        if not is_take_row:
                            # Vervolgrij: extra notitietekst aan lopende take hangen
                            if pending_clip_a is not None and notes_idx is not None:
                                extra = (row[notes_idx] or "").strip().replace("\n", " ") if notes_idx < len(row) else ""
                                if extra:
                                    pending_notes = (pending_notes + " " + extra).strip()
                            continue

                        # Sla vorige take op voordat we de nieuwe verwerken
                        if pending_clip_a:
                            if pending_clip_a not in clips:
                                clips[pending_clip_a] = {"circle": "", "scene": scene,
                                                         "description": description,
                                                         "take_notes": pending_notes or general_note}
                        if pending_clip_b:
                            if pending_clip_b not in clips:
                                clips[pending_clip_b] = {"circle": "", "scene": scene,
                                                         "description": description,
                                                         "take_notes": pending_notes or general_note}

                        clip_a = (row[clip_a_idx] or "").strip() if clip_a_idx < len(row) else ""
                        clip_b = (row[clip_b_idx] or "").strip() if clip_b_idx is not None and clip_b_idx < len(row) else ""

                        # Notities: alleen de Notes-kolom (stop voor Lengte)
                        if notes_idx is not None and notes_idx < len(row):
                            stop = notes_stop if notes_stop is not None else notes_idx + 1
                            note_parts = [(row[i] or "").strip()
                                          for i in range(notes_idx, min(stop, len(row)))]
                            notes = " ".join(p for p in note_parts if p).strip().replace("\n", " ")
                        else:
                            notes = ""
                        # Lengte-waarden die per ongeluk in Notes terechtkomen negeren
                        # (bijv. "1", "1m 20s", "40s", "50s")
                        if re.match(r"^\d+(?:\s*[ms]\w*(?:\s+\d+\s*[ms]\w*)?)?$", notes, re.I):
                            notes = ""
                        # PU-vinkje: "(PU)" voor de noot
                        if _is_pu(take_num):
                            notes = ("(PU) " + notes).strip()

                        pending_clip_a = (kaart_a + clip_a) if clip_a else None
                        pending_clip_b = (kaart_b + clip_b) if clip_b else None
                        pending_notes  = notes

                    # Laatste take opslaan
                    if pending_clip_a:
                        if pending_clip_a not in clips:
                            clips[pending_clip_a] = {"circle": "", "scene": scene,
                                                     "description": description,
                                                     "take_notes": pending_notes or general_note}
                    if pending_clip_b:
                        if pending_clip_b not in clips:
                            clips[pending_clip_b] = {"circle": "", "scene": scene,
                                                     "description": description,
                                                     "take_notes": pending_notes or general_note}
                    pending_clip_a = pending_clip_b = pending_notes = None
                continue  # Haantjes pagina verwerkt

            # ── BFF formaat: Continuïteitsrapport ──────────────────────────
            # Eén pagina per slate; clip-namen in ALE: "[scene]/[slate]-[take]"
            if re.search(r"TAKE\s+PU\s+AFG\s+CLIP", text):
                # Scene + slate uit header ("SCRIPT CONTINUÏTEIT ...\n17P1  81")
                sm = re.search(r"CONTINUÏTEIT[^\n]*\n(\S+)\s+(\d+[A-Za-z]?)", text)
                if not sm: continue
                scene = sm.group(1)            # bv. "17P1"
                slate = sm.group(2).zfill(3)  # bv. "081" of "130A"

                # Korte shot-omschrijving (regel ná "SHOT CAMERA X")
                shot_m = re.search(r"SHOT CAMERA \w\n(.+)", text)
                description = shot_m.group(1).strip() if shot_m else ""

                # Algemene NOTES-sectie (fallback voor takes zonder individuele noot)
                gnotes_m = re.search(r"AUDIO NOTES: NOTES:\n(.+)", text, re.DOTALL)
                general_note = gnotes_m.group(1).strip() if gnotes_m else ""

                # Slate-niveau entry
                if slate not in clips:
                    clips[slate] = {"circle": "", "scene": scene,
                                    "description": description, "take_notes": general_note}

                # Per-take notities uit OPMERKING-kolom
                takes_m = re.search(
                    r"TAKE\s+PU\s+AFG\s+CLIP[^\n]*\n(.*?)(?:AUDIO|$)", text, re.DOTALL)
                if takes_m:
                    for line in takes_m.group(1).split("\n"):
                        tm = re.match(r"^(\d+\w*)\s+C000\s+(.*)", line.strip())
                        if not tm: continue
                        take_id = tm.group(1)
                        rest    = tm.group(2)
                        # Strip optionele TC IN  ("0:00:00")
                        rest = re.sub(r"^\d+:\d+:\d+\s*", "", rest)
                        # Strip LENGTE — oud "0m 0s" / nieuw "m01s40ms22" / "s50ms72"
                        rest = re.sub(r"^(?:\d+m\s+\d+s|m\d+s\d+ms\d+|s\d+ms\d+)\s*", "", rest)
                        notes = rest.strip()
                        # Geen individuele noot → val terug op de algemene NOTES
                        if not notes:
                            notes = general_note
                        if not notes: continue
                        num_m = re.match(r"^(\d+)", take_id)
                        if not num_m: continue
                        key = f"{slate}-{num_m.group(1).zfill(2)}"
                        if key not in clips:
                            clips[key] = {"circle": "", "scene": scene,
                                          "description": description, "take_notes": notes}
                continue  # BFF pagina verwerkt, volgende pagina

            # ── Waste Clips ────────────────────────────────────────────────
            if "Waste Clips" in text:
                for m in re.finditer(r"(A\d{3}C\d{3})", text):
                    c = m.group(1)
                    if c not in clips:
                        clips[c] = {"circle": "X", "scene": "", "description": "", "take_notes": ""}
                continue

            has_new_hdr = bool(re.search(r"Slate\s+Take\s+Circle\s+Clip", text))
            has_old_hdr = bool(re.search(r"Take\s+Clip\s+Circle\s+Length\s+Take comment", text))

            # Formaat bijwerken als we een header zien
            if has_new_hdr:
                use_new_fmt = True
            elif has_old_hdr:
                use_new_fmt = False

            # ── NIEUW FORMAAT (ook vervolg-pagina's zonder header) ─────────
            if use_new_fmt:
                # Scene uit "Episode X - Naam - Scene Y"
                sm = re.search(r"- Scene\s+(\d+[a-zA-Z]*)", text)
                if sm: cur_scene = sm.group(1)

                # Slate-beschrijvingen bijwerken
                for line in text.split("\n"):
                    sm2 = re.match(r"^(\d{3,4})\s+(.*)", line)
                    if not sm2: continue
                    rest = sm2.group(2).strip()
                    if re.search(r"A\d{3}C\d{3}", rest):
                        # Take-regel met slate: beschrijving na clip + lengte
                        dm = re.search(r"A\d{3}C\d{3}\s+[\d:]+\s+(.*?)\s+A\d{3}\b", rest)
                        if dm and dm.group(1).strip():
                            desc = re.sub(r"\d{2}:\d{2}:\d{2}:\d{2}", "", dm.group(1)).strip()
                            desc = re.sub(r"\b\d{1,2}:\d{2}\b", "", desc).strip()
                            if desc: cur_desc = desc
                    else:
                        # Losse beschrijvingsregel: "264 Ruim" of "263 17:26:23:09 Med 2sh"
                        desc = re.sub(r"\d{2}:\d{2}:\d{2}:\d{2}", "", rest)
                        desc = re.sub(r"\b\d{1,2}:\d{2}\b", "", desc).strip()
                        if desc:
                            cur_desc = desc

                # Clips extraheren — cirkel staat VOOR de clip-code.
                # Optionele timecode (bv. "00:01:23" of "00:01:23:12") voor
                # de cirkel wordt getolereerd; pdfplumber plaatst die soms
                # vóór het ✓-symbool als de notes-kolom een TC bevat.
                for m in re.finditer(
                    r"(?:^|\n)(?:\d{3,4}\s+)?(?:\d+[A-Z0-9]*)\s+(?:\d{1,2}(?::\d{2})+\s+)?([✓\-X])\s+(A\d{3}C\d{3})(.*?)(?=\n|$)",
                    text, re.MULTILINE
                ):
                    ch   = m.group(1)
                    clip = m.group(2)
                    rest = m.group(3)
                    circle = "V" if ch == "✓" else ("X" if ch == "X" else "")

                    notes = re.sub(r"\d{2}:\d{2}:\d{2}:\d{2}", "", rest)
                    notes = re.sub(r"\bA\d{3,4}\b.*$", "", notes)
                    notes = re.sub(r"\b\d+\s*mm\b.*$", "", notes)
                    notes = re.sub(r"\b\d{1,2}:\d{2}\b", "", notes).strip()

                    if clip not in clips:
                        clips[clip] = {
                            "circle":      circle,
                            "scene":       cur_scene,
                            "description": cur_desc,
                            "take_notes":  notes,
                        }

            # ── OUD FORMAAT ────────────────────────────────────────────────
            elif has_old_hdr:
                scene = ""
                sm = re.search(r"Scene:\s+(.+)", text)
                if sm: scene = sm.group(1).replace("✓","").strip().split("\n")[0].strip()
                description = ""
                dm = re.search(r"Shot Description:\s+(.+)", text)
                if dm: description = dm.group(1).strip()
                tm = re.search(r"Take\s+Clip\s+Circle\s+Length\s+Take comment\s*\n(.*?)Shot Description:", text, re.DOTALL)
                if not tm: continue
                # Optionele timecode vóór cirkel (pdfplumber-extractie artefact)
                for m in re.finditer(r"^(\d+[A-Z]*|[A-Z]+)\s+(A\d{3}C\d{3})\s+(?:\d{1,2}(?::\d{2})+\s+)?([✓\-X])\s*(.*)", tm.group(1), re.MULTILINE):
                    clip   = m.group(2)
                    ch     = m.group(3)
                    rest   = m.group(4).strip()
                    circle = "V" if ch == "✓" else ("X" if ch == "X" else "")
                    notes  = re.sub(r"\d{2}:\d{2}:\d{2}:\d{2}", "", rest).strip()
                    notes  = re.sub(r"^\d{2}:\d{2}\s*", "", notes).strip()
                    notes  = re.sub(r"\s*\d*\s*A\d{3}C\d{3}.*$", "", notes).strip()
                    notes  = re.sub(r"\s*-\s*\d{2}:\d{2}\s*$", "", notes).strip()
                    if clip not in clips:
                        clips[clip] = {"circle": circle, "scene": scene, "description": description, "take_notes": notes}

    v = sum(1 for x in clips.values() if x["circle"] == "V")
    x = sum(1 for x in clips.values() if x["circle"] == "X")
    log(f"PDF gelezen: {len(clips)} clips  —  V: {v}  |  X: {x}", "info")
    return clips


# ---------------------------------------------------------------------------
# ALE VERWERKER
# ---------------------------------------------------------------------------

def process_ale(ale_path, clip_data, log, write_rating=True, notes_col="Auto"):
    with open(ale_path, "rb") as f:
        raw = f.read()

    # Bewaar originele line endings
    if b"\r\n" in raw:
        le = "\r\n"
    elif b"\r" in raw:
        le = "\r"
    else:
        le = "\n"

    lines = raw.decode("utf-8", errors="replace").splitlines()

    col_idx = data_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Column": col_idx = i
        if line.strip() == "Data":   data_idx = i; break
    if col_idx is None or data_idx is None:
        raise ValueError("Ongeldige ALE.")

    # Header splitsen; trailing lege kolommen afstropen (Avid voegt soms een extra \t toe)
    raw_headers = lines[col_idx + 1].split("\t")
    while raw_headers and not raw_headers[-1].strip():
        raw_headers.pop()
    col_headers = list(raw_headers)
    n_orig      = len(col_headers)

    def idx(name):
        return col_headers.index(name) if name in col_headers else None

    name_idx   = idx("Name")
    tape_idx   = idx("Tape")
    rating_idx = idx("Rating")
    scene_idx  = idx("Scene")       # alleen bijwerken als al aanwezig
    desc_idx   = idx("Description") # alleen bijwerken als al aanwezig

    # Notes-kolom: gebruik keuze van gebruiker, anders auto-detectie
    if notes_col and notes_col != "Auto":
        take_notes_idx = idx(notes_col)
        if take_notes_idx is None:
            # Kolom bestaat nog niet in ALE — voeg toe
            col_headers.append(notes_col)
            take_notes_idx = len(col_headers) - 1
            log(f"Kolom '{notes_col}' niet gevonden — toegevoegd aan ALE.", "info")
    else:
        take_notes_idx = next(
            (idx(c) for c in ("Comment", "Take_notes", "Note", "Notes", "Comments")
             if idx(c) is not None),
            None
        )
        if take_notes_idx is None:
            # Geen geschikte kolom gevonden — voeg Comment toe
            col_headers.append("Comment")
            take_notes_idx = len(col_headers) - 1
            log("Geen notes-kolom gevonden — 'Comment' toegevoegd aan ALE.", "info")

    if take_notes_idx is not None:
        log(f"Notes → kolom '{col_headers[take_notes_idx]}'", "info")

    # Alleen de kolommen die wij hebben toegevoegd krijgen een leeg veld per rij
    new_cols = col_headers[n_orig:]

    if name_idx is None:
        raise ValueError("Geen 'Name' kolom gevonden in ALE.")
    if rating_idx is None:
        log("Geen 'Rating' kolom in ALE — rating wordt overgeslagen.", "info")

    log(f"ALE kolommen ({len(col_headers)}): {', '.join(col_headers)}", "info")

    matched = 0
    new_data_lines = []
    for line in lines[data_idx + 1:]:
        if not line.strip():
            new_data_lines.append(line); continue
        parts = line.split("\t")[:n_orig]
        while len(parts) < n_orig: parts.append("")
        for _ in new_cols:
            parts.append("")
        clip_short = parts[name_idx][:8]
        info = clip_data.get(clip_short)

        # BFF formaat fallback: clip-naam "[scene]/[slate]-[take]" bv. "19A/081-02"
        if info is None:
            clip_name = parts[name_idx]
            bff_m = re.match(r'[^/]+/(\d{2,4}[A-Za-z]?)-(\w+)', clip_name)
            if bff_m:
                slate = bff_m.group(1).zfill(3)  # bv. "081" of "130A"
                take_raw = bff_m.group(2)        # bv. "02" of "03pu"
                take_num_m = re.match(r'^(\d+)', take_raw)
                if take_num_m:
                    take_key = f"{slate}-{take_num_m.group(1).zfill(2)}"
                    info = clip_data.get(take_key) or clip_data.get(slate)
                    # Fallback: slate heeft lettervariant (130A→130), zoek zonder letter
                    if info is None and re.search(r'[A-Za-z]$', slate):
                        slate_base = re.sub(r'[A-Za-z]+$', '', slate).zfill(3)
                        base_key   = f"{slate_base}-{take_num_m.group(1).zfill(2)}"
                        info = clip_data.get(base_key) or clip_data.get(slate_base)
                else:
                    info = clip_data.get(slate)
                    if info is None and re.search(r'[A-Za-z]$', slate):
                        slate_base = re.sub(r'[A-Za-z]+$', '', slate).zfill(3)
                        info = clip_data.get(slate_base)

        # Haantjes-formaat: camera clip-code staat in Tape ("A002C038_2605183D")
        if info is None and tape_idx is not None and tape_idx < len(parts):
            tape_key = parts[tape_idx][:8]
            info = clip_data.get(tape_key)

        if info:
            matched += 1
            if write_rating and rating_idx is not None and info["circle"]:
                parts[rating_idx] = info["circle"]
            if take_notes_idx is not None and info["take_notes"]:
                parts[take_notes_idx] = info["take_notes"].replace("\n", " ").replace("\r", " ")
            if scene_idx is not None and info["scene"]:
                parts[scene_idx] = info["scene"].replace("\n", " ").replace("\r", " ")
            if desc_idx is not None and info["description"]:
                parts[desc_idx] = info["description"].replace("\n", " ").replace("\r", " ")
        new_data_lines.append("\t".join(parts) + "\t")

    log(f"ALE verwerkt: {matched} clips bijgewerkt", "info")
    out_lines = lines[:col_idx] + ["Column", "\t".join(col_headers) + "\t", "", "Data"] + new_data_lines
    result = le.join(out_lines)
    if raw.endswith(le.encode()):
        result += le
    return result


# ---------------------------------------------------------------------------
# GUI  —  Avid-stijl kleurenpalet
# ---------------------------------------------------------------------------

VERSION       = "1.0 (Beta)"
GITHUB_REPO   = "scprdytj2s-beep/continuity-bridge"
RELEASES_URL  = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"

# ---------------------------------------------------------------------------
# LICENTIE
# Serialformaat: CB-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX  (24 base32-chars na CB-)
#   bytes 0-1  : vervaldatum (uint16, dagen sinds 2024-01-01)
#   bytes 2-9  : naam (UTF-8, null-padded tot 8 bytes, max 8 tekens)
#   bytes 10-14: HMAC-SHA256 eerste 5 bytes  → totaal 15 bytes
# ---------------------------------------------------------------------------
import hmac as _hmac, hashlib as _hashlib, struct as _struct
import base64 as _b64, json as _json
from datetime import date as _date, timedelta as _td

_LIC_KEY    = b'CB2026-ContBridge-HMAC-S3cr3t-K3y'
_LIC_EPOCH  = _date(2024, 1, 1)
_LIC_DIR    = Path.home() / ".continuitybridge"
_LIC_FILE   = _LIC_DIR / "license"
_REVOKE_URL = (f"https://raw.githubusercontent.com/"
               f"scprdytj2s-beep/continuity-bridge/main/revoked.json")

# Module-level: revocatielijst geladen bij opstarten (achtergrond)
_revoked_serials: set = set()


def _serial_generate(name: str, expiry: _date) -> str:
    """Genereer serial met naam + vervaldatum."""
    name_b  = name.encode('utf-8')[:8].ljust(8, b'\x00')
    days    = (expiry - _LIC_EPOCH).days
    payload = _struct.pack('>H', days) + name_b          # 10 bytes
    sig     = _hmac.new(_LIC_KEY, payload, _hashlib.sha256).digest()[:5]
    b32     = _b64.b32encode(payload + sig).decode()     # 24 chars, geen padding
    return f"CB-{b32[:4]}-{b32[4:8]}-{b32[8:12]}-{b32[12:16]}-{b32[16:20]}-{b32[20:]}"


def _serial_verify(serial: str):
    """Verifieer serial.
    Returns (ok: bool, expiry: date|None, name: str, msg: str)."""
    clean = serial.upper().replace('-', '').replace(' ', '')
    if clean.startswith('CB'):
        clean = clean[2:]
    try:
        if len(clean) != 24:
            return False, None, "", "Ongeldig formaat."
        raw  = _b64.b32decode(clean)                     # 15 bytes
        days = _struct.unpack('>H', raw[:2])[0]
        name = raw[2:10].rstrip(b'\x00').decode('utf-8', errors='replace')
        sig_stored   = raw[10:15]
        sig_expected = _hmac.new(_LIC_KEY, raw[:10], _hashlib.sha256).digest()[:5]
        if not _hmac.compare_digest(sig_stored, sig_expected):
            return False, None, name, "Ongeldige licentiesleutel."
        expiry = _LIC_EPOCH + _td(days=days)
        norm   = serial.upper().replace(' ', '')
        if norm in _revoked_serials:
            return False, expiry, name, "Licentie ingetrokken."
        if _date.today() >= expiry:
            return False, expiry, name, f"Verlopen op {expiry.strftime('%d-%m-%Y')}."
        return True, expiry, name, f"Geldig t/m {expiry.strftime('%d-%m-%Y')}"
    except Exception:
        return False, None, "", "Ongeldig serienummer."


def _serial_verify_with_machine(serial: str, stored_machine_id: str):
    """Verifieer serial én machine-binding."""
    ok, expiry, name, msg = _serial_verify(serial)
    if not ok:
        return False, expiry, name, msg
    current_uuid = _machine_uuid()
    if stored_machine_id and stored_machine_id != "UNKNOWN" \
            and stored_machine_id != current_uuid:
        return False, expiry, name, "Licentie gebonden aan andere Mac."
    return True, expiry, name, msg


def _fetch_revoked_list():
    """Haal revocatielijst op: eerst lokaal (manager-bestand), dan GitHub."""
    global _revoked_serials
    combined: set = set()

    # 1. Lokale check: lees licenses.json van de manager (zelfde Mac)
    try:
        _local_lic_db = Path.home() / ".continuitybridge" / "licenses.json"
        if _local_lic_db.exists():
            db = _json.loads(_local_lic_db.read_text())
            for entry in db:
                if entry.get('revoked'):
                    combined.add(entry['serial'].upper().replace(' ', ''))
    except Exception:
        pass

    # 2. GitHub revocatielijst (werkt ook op andere Macs)
    try:
        import urllib.request
        req = urllib.request.Request(_REVOKE_URL,
              headers={"User-Agent": "ContinuityBridge"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _json.loads(r.read())
        for s in data:
            combined.add(s.upper().replace(' ', ''))
    except Exception:
        pass   # geen internet / bestand bestaat nog niet

    if combined:
        _revoked_serials = combined


def _machine_uuid() -> str:
    """Unieke hardware-ID: macOS via ioreg, Windows via wmic."""
    import sys as _sys
    try:
        if _sys.platform == 'darwin':
            import subprocess as _sp
            out = _sp.run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                          capture_output=True, text=True).stdout
            for line in out.splitlines():
                if 'IOPlatformUUID' in line:
                    return line.split('"')[-2]
        elif _sys.platform == 'win32':
            import subprocess as _sp
            out = _sp.run(['wmic', 'csproduct', 'get', 'UUID'],
                          capture_output=True, text=True, shell=True).stdout
            for line in out.splitlines():
                line = line.strip()
                if line and line.upper() != 'UUID':
                    return line
    except Exception:
        pass
    return "UNKNOWN"


def _license_load():
    """Returns (serial, machine_id) of (None, None)."""
    try:
        data = _json.loads(_LIC_FILE.read_text())
        return data.get('serial', ''), data.get('machine_id', '')
    except Exception:
        return None, None


def _license_save(serial: str):
    _LIC_DIR.mkdir(parents=True, exist_ok=True)
    _LIC_FILE.write_text(_json.dumps({
        'serial':     serial.strip(),
        'machine_id': _machine_uuid()
    }))


def _license_delete():
    try:
        _LIC_FILE.unlink()
    except Exception:
        pass


# Continuity Bridge kleurpallet — gebaseerd op app-icoon (diep paars)
BG       = "#130828"   # diepe achtergrond
SURFACE  = "#1F1040"   # kaartachtergrond
SURFACE2 = "#2C1A58"   # hover / actief
BORDER   = "#3D2278"   # subtiele paarse rand
TEXT     = "#EDE8FF"   # bijna-wit met paarse tint
MUTED    = "#8070B8"   # gedempte subtekst
AVID_B   = "#6B28D4"   # primair paars (knop, header)
AVID_B_H = "#5820B0"   # hover primair
SUCCESS  = "#4ED98A"
ERROR    = "#FF5577"


def _rrect(cv, w, h, r, color, fg, text, font):
    """Teken afgerond rechthoek + tekst op canvas cv."""
    import tkinter.font as _tf
    cv.delete("all")
    r = min(r, w // 2, h // 2)
    kw = dict(fill=color, outline="")
    cv.create_arc(0,     0,     2*r, 2*r, start=90,  extent=90, style="pieslice", **kw)
    cv.create_arc(w-2*r, 0,     w,   2*r, start=0,   extent=90, style="pieslice", **kw)
    cv.create_arc(0,     h-2*r, 2*r, h,   start=180, extent=90, style="pieslice", **kw)
    cv.create_arc(w-2*r, h-2*r, w,   h,   start=270, extent=90, style="pieslice", **kw)
    cv.create_rectangle(r, 0, w-r, h, **kw)
    cv.create_rectangle(0, r, w, h-r, **kw)
    cv.create_text(w // 2, h // 2, text=text, fill=fg, font=font)


def _rounded_btn(parent, text, cmd, bg, hv, fg, font, px=14, py=7, r=10, pbg=None):
    """Canvas-knop met afgeronde hoeken. Geeft canvas terug."""
    import tkinter.font as _tf
    _f  = _tf.Font(family=font[0], size=font[1],
                   weight=font[2] if len(font) > 2 else "normal")
    _w  = _f.measure(text) + px * 2
    _h  = _f.metrics("linespace") + py * 2
    _bg = pbg or (parent.cget("bg") if hasattr(parent, "cget") else BG)
    cv  = tk.Canvas(parent, width=_w, height=_h, bd=0,
                    highlightthickness=0, bg=_bg, cursor="arrow")
    _rrect(cv, _w, _h, r, bg, fg, text, font)
    cv.bind("<Enter>",    lambda e: _rrect(cv, _w, _h, r, hv, fg, text, font))
    cv.bind("<Leave>",    lambda e: _rrect(cv, _w, _h, r, bg, fg, text, font))
    cv.bind("<Button-1>", lambda e: cmd())
    return cv


class App:
    NOTES_COLS = ["Auto", "Comment", "Note", "Take_notes", "Comments", "Notes"]

    def __init__(self, root):
        self.root = root
        self.pdf_path     = tk.StringVar()
        self.ale_path     = tk.StringVar()
        self.write_rating = tk.BooleanVar(value=False)
        self.notes_col    = tk.StringVar(value="Auto")
        self.root.title("Continuity Bridge")
        self.root.geometry("520x510")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        # ── Update-check ─────────────────────────────────────────────────────
        def _check_updates(silent=False):
            """Check GitHub releases. silent=True → alleen tonen bij nieuwere versie."""
            import urllib.request, json
            def _do():
                try:
                    req = urllib.request.Request(RELEASES_URL,
                          headers={"User-Agent": "ContinuityBridge"})
                    with urllib.request.urlopen(req, timeout=5) as r:
                        releases = json.loads(r.read())
                    # /releases geeft een lijst terug (incl. pre-releases),
                    # gepubliceerd op datum gesorteerd. Pak de eerste (meest recent).
                    data = releases[0] if isinstance(releases, list) and releases else {}
                    latest = data.get("tag_name", "").lstrip("v")
                    def _vt(v):
                        import re as _re
                        nums = _re.findall(r'\d+', v)
                        return tuple(int(x) for x in nums)
                    newer = _vt(latest) > _vt(VERSION)
                    def _show():
                        if newer:
                            if tk.messagebox.askyesno(
                                "Update beschikbaar",
                                f"Versie {latest} is beschikbaar (jij hebt {VERSION}).\n"
                                "Openen in browser?"):
                                import webbrowser
                                webbrowser.open(RELEASES_PAGE)
                        elif not silent:
                            tk.messagebox.showinfo(
                                "Geen updates",
                                f"Je hebt de nieuwste versie ({VERSION}).")
                    self.root.after(0, _show)
                except Exception:
                    if not silent:
                        self.root.after(0, lambda: tk.messagebox.showwarning(
                            "Update-check mislukt",
                            "Kan geen verbinding maken met GitHub."))
            threading.Thread(target=_do, daemon=True).start()

        # ── About-venster ────────────────────────────────────────────────────
        def _show_about():
            win = tk.Toplevel(self.root)
            win.title("Over Continuity Bridge")
            win.resizable(False, False)
            win.configure(bg=BG)
            win.geometry("340x280")
            win.lift()
            win.focus_force()
            try:
                img = tk.PhotoImage(file=str(Path(__file__).parent / "AppIcon.png"))
                img = img.subsample(max(1, img.width() // 64))
                lbl_img = tk.Label(win, image=img, bg=BG)
                lbl_img.image = img
                lbl_img.pack(pady=(20, 6))
            except Exception:
                pass
            tk.Label(win, text="Continuity Bridge", bg=BG, fg=TEXT,
                     font=("Helvetica Neue", 15, "bold")).pack()
            tk.Label(win, text=f"Versie {VERSION}", bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 11)).pack(pady=(2, 0))
            tk.Label(win, text="by Michiel Boesveldt  © 2026", bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 11)).pack(pady=(2, 4))
            _mail = tk.Label(win, text="support@studiomichielboesveldt.nl",
                             bg=BG, fg=AVID_B,
                             font=("Helvetica Neue", 10, "underline"),
                             cursor="pointinghand")
            _mail.pack(pady=(0, 14))
            _mail.bind("<Button-1>", lambda e: __import__('webbrowser').open(
                "mailto:support@studiomichielboesveldt.nl"))
            _rounded_btn(win, "OK", win.destroy,
                         bg=AVID_B, hv=AVID_B_H, fg="white",
                         font=("Helvetica Neue", 12, "bold"),
                         px=28, py=6, r=10, pbg=BG).pack()
            win.bind("<Return>", lambda e: win.destroy())
            win.bind("<Escape>", lambda e: win.destroy())

        # ── Licentiedialoog ──────────────────────────────────────────────────
        def _show_license_dialog(message="", block=False):
            """Toon dialoog voor serial invoer. block=True → app sluit bij annuleren."""
            dlg = tk.Toplevel(self.root)
            dlg.title("Licentie activeren")
            dlg.resizable(False, False)
            dlg.configure(bg=BG)
            dlg.geometry("400x420")
            dlg.grab_set()
            dlg.lift()
            dlg.focus_force()

            tk.Label(dlg, text="Continuity Bridge", bg=BG, fg=TEXT,
                     font=("Helvetica Neue", 14, "bold")).pack(pady=(20, 4))

            if message:
                tk.Label(dlg, text=message, bg=BG, fg=ERROR,
                         font=("Helvetica Neue", 10)).pack(pady=(4, 0))

            tk.Label(dlg, text="Naam", bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 10)).pack(pady=(10, 3))
            name_var = tk.StringVar()
            name_entry = tk.Entry(dlg, textvariable=name_var, bg=SURFACE2, fg=TEXT,
                                  insertbackground=TEXT, relief="flat",
                                  font=("Helvetica Neue", 12), width=26,
                                  justify="center")
            name_entry.pack(ipady=6)
            name_entry.focus_set()

            tk.Label(dlg, text="Serienummer", bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 10)).pack(pady=(10, 3))
            serial_var = tk.StringVar()
            entry = tk.Entry(dlg, textvariable=serial_var, bg=SURFACE2, fg=TEXT,
                             insertbackground=TEXT, relief="flat",
                             font=("Helvetica Neue", 11), width=26,
                             justify="center")
            entry.pack(ipady=6)

            status_lbl = tk.Label(dlg, text="", bg=BG, fg=MUTED,
                                  font=("Helvetica Neue", 10))
            status_lbl.pack(pady=(8, 0))

            def _activate():
                ok, expiry, serial_name, msg = _serial_verify(serial_var.get())
                if not ok:
                    status_lbl.config(fg=ERROR, text=f"✗ {msg}")
                    return
                entered_name = name_var.get().strip()
                # Vergelijk eerste 8 UTF-8 bytes (zelfde truncatie als generatie)
                entered_trunc = entered_name.encode('utf-8')[:8].ljust(8, b'\x00') \
                                            .rstrip(b'\x00').decode('utf-8', errors='replace')
                if entered_trunc.lower() != serial_name.lower():
                    status_lbl.config(fg=ERROR,
                        text="✗ Naam komt niet overeen met licentie.")
                    return
                _license_save(serial_var.get())
                self._license_expiry = expiry
                status_lbl.config(fg=SUCCESS,
                    text=f"✓ Welkom, {serial_name}!  {msg}")
                dlg.after(1000, dlg.destroy)

            def _cancel():
                if block:
                    self.root.destroy()
                else:
                    dlg.destroy()

            dlg.protocol("WM_DELETE_WINDOW", _cancel)

            _act_cv = _rounded_btn(dlg, "Activeer", _activate,
                                    bg=AVID_B, hv=AVID_B_H, fg="white",
                                    font=("Helvetica Neue", 12, "bold"),
                                    px=24, py=7, r=10, pbg=BG)
            _act_cv.pack(pady=(8, 0))
            name_entry.bind("<Return>", lambda e: entry.focus_set())
            entry.bind("<Return>", lambda e: _activate())

            if block:
                _SHOP_URL = "https://payment-links.mollie.com/payment/NesoriUjVmqbLs84L5mrP"
                _shop_cv  = _rounded_btn(dlg, "🛒  Koop licentie",
                                         lambda: __import__('webbrowser').open(_SHOP_URL),
                                         bg=SUCCESS, hv="#3ab870", fg="#0A2A10",
                                         font=("Helvetica Neue", 11, "bold"),
                                         px=18, py=6, r=10, pbg=BG)
                _shop_cv.pack(pady=(12, 0))
                tk.Label(dlg, text="Na betaling ontvang je serial per mail.",
                         bg=BG, fg=MUTED, font=("Helvetica Neue", 9)).pack(pady=(6, 0))
                mail_lbl = tk.Label(dlg, text="support@studiomichielboesveldt.nl",
                                    bg=BG, fg=AVID_B,
                                    font=("Helvetica Neue", 9, "underline"),
                                    cursor="pointinghand")
                mail_lbl.pack(pady=(2, 0))
                mail_lbl.bind("<Button-1>", lambda e: __import__('webbrowser').open(
                    "mailto:support@studiomichielboesveldt.nl"))

        def _show_license_info():
            def _do_show():
                _fetch_revoked_list()   # fetch in thread, max 5s
                serial, mid = _license_load()
                if serial:
                    ok, expiry, name, msg = _serial_verify_with_machine(serial, mid)
                else:
                    ok, expiry, name, msg = False, None, "", "Geen licentie."
                def _render():
                    if ok:
                        win = tk.Toplevel(self.root)
                        win.title("Licentie")
                        win.resizable(False, False)
                        win.configure(bg=BG)
                        win.geometry("340x230")
                        win.grab_set(); win.lift(); win.focus_force()
                        tk.Label(win, text="✓  Actief", bg=BG, fg=SUCCESS,
                                 font=("Helvetica Neue", 13, "bold")).pack(pady=(20, 4))
                        tk.Label(win, text=name, bg=BG, fg=TEXT,
                                 font=("Helvetica Neue", 14, "bold")).pack()
                        tk.Label(win, text=msg, bg=BG, fg=MUTED,
                                 font=("Helvetica Neue", 11)).pack(pady=(4, 10))
                        tk.Label(win, text=serial, bg=BG, fg=MUTED,
                                 font=("Menlo", 9), wraplength=300).pack(pady=(0, 8))
                        _sl = tk.Label(win, text="support@studiomichielboesveldt.nl",
                                       bg=BG, fg=AVID_B,
                                       font=("Helvetica Neue", 9, "underline"),
                                       cursor="pointinghand")
                        _sl.pack(pady=(0, 10))
                        _sl.bind("<Button-1>", lambda e: __import__('webbrowser').open(
                            "mailto:support@studiomichielboesveldt.nl"))
                        _rounded_btn(win, "OK", win.destroy,
                                     bg=AVID_B, hv=AVID_B_H, fg="white",
                                     font=("Helvetica Neue", 12, "bold"),
                                     px=28, py=6, r=10, pbg=BG).pack()
                        win.bind("<Return>", lambda e: win.destroy())
                        win.bind("<Escape>", lambda e: win.destroy())
                    else:
                        if ok is False and serial and msg not in ("Geen licentie.",):
                            # revoked / expired → block
                            _license_delete()
                            self._license_expiry = None
                            _show_license_dialog(message=msg, block=True)
                        elif tk.messagebox.askyesno("Licentie", f"{msg}\n\nNieuw serienummer invoeren?"):
                            _show_license_dialog()
                self.root.after(0, _render)
            threading.Thread(target=_do_show, daemon=True).start()

        def _remove_license():
            if tk.messagebox.askyesno("Licentie verwijderen",
                    "Licentie verwijderen van deze Mac?\n\n"
                    "Je moet daarna een nieuw serienummer invoeren."):
                _license_delete()
                self._license_expiry = None
                _show_license_dialog(
                    message="Licentie verwijderd. Voer een nieuw serienummer in.",
                    block=True)

        # ── Revocatielijst ophalen vóór licenticheck ─────────────────────────
        # Blokkeer main thread kort (max 3s) zodat check altijd actuele lijst heeft.
        # Na startup: background thread herhaalt check om ook later-ingetrokken licenties
        # te detecteren als de app al open is.
        import threading as _threading_mod
        _revoke_done = _threading_mod.Event()

        def _bg_fetch():
            _fetch_revoked_list()
            _revoke_done.set()

        _threading_mod.Thread(target=_bg_fetch, daemon=True).start()
        _revoke_done.wait(timeout=3)   # wacht max 3s op fetch

        # ── Licenticheck bij opstarten ────────────────────────────────────────
        serial, mid = _license_load()
        if serial:
            ok, expiry, name, msg = _serial_verify_with_machine(serial, mid)
            if ok:
                self._license_expiry = expiry
            else:
                _license_delete()
                self._license_expiry = None
                self.root.after(100, lambda m=msg: _show_license_dialog(message=m, block=True))
        else:
            self._license_expiry = None
            self.root.after(100, lambda: _show_license_dialog(block=True))

        # ── macOS menubalk + apple-menu ───────────────────────────────────────
        try:
            _menubar = tk.Menu(self.root)

            # App-menu (macOS apple-menu)
            _appmenu = tk.Menu(_menubar, name='apple', tearoff=False)
            _appmenu.add_command(label='Over Continuity Bridge', command=_show_about)
            _menubar.add_cascade(label='Continuity Bridge', menu=_appmenu)

            # Help-menu
            _helpmenu = tk.Menu(_menubar, tearoff=False)
            _helpmenu.add_command(label='Licentie…', command=_show_license_info)
            _helpmenu.add_command(label='Verwijder licentie…', command=_remove_license)
            _helpmenu.add_separator()
            _helpmenu.add_command(label='Check voor updates…',
                                  command=lambda: _check_updates(silent=False))
            _menubar.add_cascade(label='Help', menu=_helpmenu)

            self.root.config(menu=_menubar)
            self.root.createcommand('tk::mac::ShowAbout', _show_about)
        except Exception:
            pass

        # Startup update-check (stil — alleen tonen bij nieuwere versie)
        self.root.after(2000, lambda: _check_updates(silent=True))

        # ── Periodieke revocatie-hercheck (elke 5 min) ───────────────────────
        def _periodic_revoke_check():
            def _do():
                _fetch_revoked_list()
                serial, mid = _license_load()
                if not serial:
                    return
                ok, expiry, name, msg = _serial_verify_with_machine(serial, mid)
                if not ok:
                    def _block():
                        _license_delete()
                        self._license_expiry = None
                        _show_license_dialog(message=msg, block=True)
                    self.root.after(0, _block)
            _threading_mod.Thread(target=_do, daemon=True).start()
            self.root.after(5 * 60 * 1000, _periodic_revoke_check)   # elke 5 min

        self.root.after(5 * 60 * 1000, _periodic_revoke_check)

        self._ui()
        if HAS_NATIVE_DND and not HAS_DND:
            self.root.after(300, self._setup_native_dnd)

    def _setup_native_dnd(self):
        """Bestandsdrop via ctypes ObjC-runtime (bypast PyObjC protocol-check)."""
        import ctypes

        app_ref = self
        # Queue: ctypes ObjC callback schrijft pad hierin, poller leest het.
        # Zo raakt root.after() nooit aangeroepen vanuit een ctypes-context,
        # wat in Python 3.14 een PyEval_RestoreThread(NULL)-crash geeft.
        _drop_queue = _queue.Queue()

        def _poll_drops():
            """Draait periodiek in de normale Tk event-loop — thread state altijd geldig."""
            try:
                while True:
                    filepath = _drop_queue.get_nowait()
                    p = Path(filepath)
                    ext = p.suffix.lower()
                    if ext == ".pdf":
                        app_ref.pdf_path.set(filepath)
                        app_ref.pdf_lbl.config(text=p.name, fg=TEXT)
                        app_ref._log_direct(f"PDF:  {p.name}", "info")
                    elif ext in (".ale", ".txt"):
                        app_ref.ale_path.set(filepath)
                        app_ref.ale_lbl.config(text=p.name, fg=TEXT)
                        app_ref._log_direct(f"ALE:  {p.name}", "info")
                    else:
                        app_ref._log_direct(f"Onbekend bestandstype: {p.name}", "info")
            except _queue.Empty:
                pass
            app_ref.root.after(50, _poll_drops)

        # Start de poller vanuit normale Python-context (veilig voor PythonCmd)
        app_ref.root.after(50, _poll_drops)

        def attach():
            try:
                our_win = None
                for win in _NSApp.sharedApplication().windows():
                    if win.title() == "Continuity Bridge":
                        our_win = win
                        break
                if our_win is None:
                    app_ref.root.after(200, attach)
                    return

                cv  = our_win.contentView()
                vc  = type(cv)   # TKContentView

                if getattr(vc, "_ale_dnd_ready", False):
                    cv.registerForDraggedTypes_(["NSFilenamesPboardType"])
                    return

                # ── ObjC runtime via ctypes ──────────────────────────────
                libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')

                libobjc.objc_getClass.restype        = ctypes.c_void_p
                libobjc.objc_getClass.argtypes       = [ctypes.c_char_p]
                libobjc.sel_registerName.restype     = ctypes.c_void_p
                libobjc.sel_registerName.argtypes    = [ctypes.c_char_p]
                libobjc.class_replaceMethod.restype  = ctypes.c_void_p
                libobjc.class_replaceMethod.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.c_char_p,
                ]

                cls_ptr = libobjc.objc_getClass(b'TKContentView')
                if not cls_ptr:
                    return   # klasse niet gevonden

                # Adres van objc_msgSend voor getypeerde wrappers
                _sa = ctypes.cast(libobjc.objc_msgSend, ctypes.c_void_p).value

                # Hulp: getypeerde aanroepen via objc_msgSend ──────────────
                def _p(obj, sel):
                    """(obj, sel) → id"""
                    return ctypes.CFUNCTYPE(
                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
                    )(_sa)(obj, sel)

                def _p_p(obj, sel, arg):
                    """(obj, sel, id) → id"""
                    return ctypes.CFUNCTYPE(
                        ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_void_p
                    )(_sa)(obj, sel, arg)

                def _p_u(obj, sel, idx_):
                    """(obj, sel, NSUInteger) → id"""
                    return ctypes.CFUNCTYPE(
                        ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_uint64
                    )(_sa)(obj, sel, idx_)

                def _u(obj, sel):
                    """(obj, sel) → NSUInteger"""
                    return ctypes.CFUNCTYPE(
                        ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p
                    )(_sa)(obj, sel)

                def _cs(obj, sel):
                    """(obj, sel) → const char*"""
                    return ctypes.CFUNCTYPE(
                        ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p
                    )(_sa)(obj, sel)

                # Selectors ────────────────────────────────────────────────
                SEL_pb    = libobjc.sel_registerName(b'draggingPasteboard')
                SEL_types = libobjc.sel_registerName(b'types')
                SEL_count = libobjc.sel_registerName(b'count')
                SEL_obj   = libobjc.sel_registerName(b'objectAtIndex:')
                SEL_plist = libobjc.sel_registerName(b'propertyListForType:')
                SEL_utf8  = libobjc.sel_registerName(b'UTF8String')

                # NSFilenamesPboardType NSString via ctypes
                NSStr_cls = libobjc.objc_getClass(b'NSString')
                SEL_swu   = libobjc.sel_registerName(b'stringWithUTF8String:')
                _nsfpt    = ctypes.CFUNCTYPE(
                    ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.c_char_p
                )(_sa)(NSStr_cls, SEL_swu, b'NSFilenamesPboardType')

                # Helpers ──────────────────────────────────────────────────
                def _has_file_types(sender_p):
                    try:
                        pb = _p(sender_p, SEL_pb)
                        if not pb: return False
                        tys = _p(pb, SEL_types)
                        if not tys: return False
                        n = _u(tys, SEL_count)
                        for i in range(n):
                            t = _p_u(tys, SEL_obj, i)
                            if t and _cs(t, SEL_utf8) == b'NSFilenamesPboardType':
                                return True
                    except Exception:
                        pass
                    return False

                def _get_files(sender_p):
                    try:
                        pb  = _p(sender_p, SEL_pb)
                        if not pb: return []
                        arr = _p_p(pb, SEL_plist, _nsfpt)
                        if not arr: return []
                        n   = _u(arr, SEL_count)
                        out = []
                        for i in range(n):
                            item = _p_u(arr, SEL_obj, i)
                            if item:
                                s = _cs(item, SEL_utf8)
                                if s:
                                    out.append(s.decode('utf-8', errors='replace'))
                        return out
                    except Exception:
                        return []

                # IMP-types ────────────────────────────────────────────────
                DragOpIMP = ctypes.CFUNCTYPE(
                    ctypes.c_uint64,
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
                BoolIMP   = ctypes.CFUNCTYPE(
                    ctypes.c_int8,
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
                VoidIMP   = ctypes.CFUNCTYPE(
                    None,
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

                def _imp_entered(s, se, sender):
                    return int(_DND_COPY) if _has_file_types(sender) else 0

                def _imp_updated(s, se, sender):
                    return int(_DND_COPY) if _has_file_types(sender) else 0

                def _imp_prepare(s, se, sender):
                    return 1

                def _imp_perform(s, se, sender):
                    try:
                        files = _get_files(sender)
                        if files:
                            # Alleen queue-put — GEEN root.after() vanuit ctypes-context
                            # (Python 3.14: PyEval_RestoreThread(NULL) = fatal crash)
                            _drop_queue.put(files[0])
                        return 1
                    except Exception:
                        return 0

                def _imp_exited(s, se, sender):
                    pass

                # Ctypes callbacks — moeten in leven blijven (opgeslagen op klasse)
                _imps = (
                    DragOpIMP(_imp_entered),
                    DragOpIMP(_imp_updated),
                    BoolIMP(_imp_prepare),
                    BoolIMP(_imp_perform),
                    VoidIMP(_imp_exited),
                )

                SEL_entered = libobjc.sel_registerName(b'draggingEntered:')
                SEL_updated = libobjc.sel_registerName(b'draggingUpdated:')
                SEL_prepare = libobjc.sel_registerName(b'prepareForDragOperation:')
                SEL_perform = libobjc.sel_registerName(b'performDragOperation:')
                SEL_exited  = libobjc.sel_registerName(b'draggingExited:')

                libobjc.class_replaceMethod(cls_ptr, SEL_entered, _imps[0], b'Q@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_updated, _imps[1], b'Q@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_prepare, _imps[2], b'B@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_perform, _imps[3], b'B@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_exited,  _imps[4], b'v@:@')

                vc._ale_imps      = _imps   # voorkomt garbage collection
                vc._ale_dnd_ready = True

                cv.registerForDraggedTypes_(["NSFilenamesPboardType"])

            except Exception:
                pass   # DnD werkt niet — geen crash

        attach()

    def _ui(self):
        # ── Header (gradient canvas) ─────────────────────────────────────────
        _HDR_H  = 52
        _GL     = (0x9B, 0x40, 0xFF)   # links: elektrisch violet
        _GR     = (0x1A, 0x05, 0x45)   # rechts: diep indigo

        hdr_cv = tk.Canvas(self.root, height=_HDR_H, bd=0, highlightthickness=0)
        hdr_cv.pack(fill="x")

        def _draw_hdr(event=None):
            w = hdr_cv.winfo_width()
            if w < 2:
                hdr_cv.after(20, _draw_hdr); return
            hdr_cv.delete("all")
            step = max(1, w // 300)
            for x in range(0, w + step, step):
                t = min(x / (w - 1), 1.0)
                r = int(_GL[0] + (_GR[0] - _GL[0]) * t)
                g = int(_GL[1] + (_GR[1] - _GL[1]) * t)
                b = int(_GL[2] + (_GR[2] - _GL[2]) * t)
                hdr_cv.create_rectangle(x, 0, x + step, _HDR_H,
                                        fill=f"#{r:02x}{g:02x}{b:02x}", outline="")
            hdr_cv.create_text(22, _HDR_H // 2,
                               text="✦  Continuity Bridge", anchor="w",
                               fill="white", font=("Helvetica Neue", 15, "bold"))
            hdr_cv.create_text(w - 18, _HDR_H // 2,
                               text=f"v{VERSION}", anchor="e",
                               fill="#C0A0FF", font=("Helvetica Neue", 10))

        hdr_cv.bind("<Configure>", _draw_hdr)

        # ── Body ─────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG, pady=22, padx=22)
        body.pack(fill="x")

        # Sectielabels met lichte paarse tint
        def _section_label(parent, text):
            tk.Label(parent, text=text.upper(), bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 9, "bold"), anchor="w").pack(fill="x", pady=(0, 6))

        _section_label(body, "1  Avid Bin ALE")
        self._file_row(body, self.ale_path, self._pick_ale, "ale_lbl",
                       self._drop_ale).pack(fill="x", pady=(0, 18))

        _section_label(body, "2  Continuïteitsrapport (PDF)")
        self._file_row(body, self.pdf_path, self._pick_pdf, "pdf_lbl",
                       self._drop_pdf).pack(fill="x", pady=(0, 22))

        # ── Opties ───────────────────────────────────────────────────────────
        # Dunne scheidingslijn
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))

        opts = tk.Frame(body, bg=BG)
        opts.pack(fill="x", pady=(0, 14))

        chk = tk.Checkbutton(opts, text="Schrijf rating  (V / X)",
                             variable=self.write_rating,
                             bg=BG, fg=TEXT, selectcolor=SURFACE2,
                             activebackground=BG, activeforeground=TEXT,
                             font=("Helvetica Neue", 11), anchor="w",
                             cursor="arrow", relief="flat", bd=0)
        chk.pack(side="left")

        tk.Label(opts, text="Notes →", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(18, 5))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("CB.TCombobox",
                        fieldbackground=SURFACE2, background=SURFACE2,
                        foreground=TEXT, selectbackground=AVID_B,
                        selectforeground="white", arrowcolor=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        insertcolor=TEXT, relief="flat", padding=4)
        style.map("CB.TCombobox",
                  fieldbackground=[("readonly", SURFACE2)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", SURFACE2)],
                  selectforeground=[("readonly", TEXT)],
                  background=[("active", SURFACE2), ("readonly", SURFACE2)])

        # Dropdown-listbox kleuren via Tk option database (werkt wel op macOS)
        self.root.option_add("*TCombobox*Listbox.background",       SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground",       TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", AVID_B)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font",             "{{Helvetica Neue} 11}")
        self.root.option_add("*TCombobox*Listbox.relief",           "flat")
        self.root.option_add("*TCombobox*Listbox.borderWidth",      "0")

        cb = ttk.Combobox(opts, textvariable=self.notes_col,
                          values=self.NOTES_COLS, state="readonly", width=11,
                          style="CB.TCombobox", font=("Helvetica Neue", 11))
        cb.pack(side="left")

        # ── Verwerk-knop (afgeronde Canvas, full-width) ──────────────────────
        _VF = ("Helvetica Neue", 14, "bold")
        _VH = 48   # hoogte
        _VR = 12   # hoek-radius
        self._btn_enabled = True
        self.btn = tk.Canvas(body, height=_VH, bd=0, highlightthickness=0, bg=BG, cursor="arrow")
        self.btn.pack(fill="x")

        def _draw_verwerk(color, label="Verwerk", fg="#FFFFFF"):
            w = self.btn.winfo_width()
            if w < 2: return
            _rrect(self.btn, w, _VH, _VR, color, fg, label, _VF)

        def _on_verwerk_resize(e):
            clr = AVID_B if self._btn_enabled else SURFACE2
            lbl = "Verwerk" if self._btn_enabled else "Bezig…"
            _draw_verwerk(clr, lbl)

        self.btn.bind("<Configure>", _on_verwerk_resize)

        def _btn_enter(e):
            if self._btn_enabled: _draw_verwerk(AVID_B_H)
        def _btn_leave(e):
            if self._btn_enabled: _draw_verwerk(AVID_B)
        def _btn_click(e):
            if self._btn_enabled: self._run()

        self.btn.bind("<Enter>",    _btn_enter)
        self.btn.bind("<Leave>",    _btn_leave)
        self.btn.bind("<Button-1>", _btn_click)

        # Sla _draw_verwerk op voor gebruik in _process
        self._draw_verwerk = _draw_verwerk

        # ── Log ──────────────────────────────────────────────────────────────
        log_outer = tk.Frame(self.root, bg=BORDER, padx=1, pady=1,
                             bd=0, highlightthickness=0)
        log_outer.pack(fill="both", expand=True, padx=22, pady=(16, 18))
        log_frame = tk.Frame(log_outer, bg=SURFACE, bd=0, highlightthickness=0)
        log_frame.pack(fill="both", expand=True)

        self.log_box = tk.Text(log_frame, bg=SURFACE, fg=MUTED,
            font=("Menlo", 10), relief="flat", bd=0, highlightthickness=0,
            padx=14, pady=12, wrap="word", state="disabled", height=6,
            cursor="arrow")
        log_sb = tk.Scrollbar(log_frame, orient="vertical",
                              command=self.log_box.yview,
                              bg=SURFACE2, troughcolor=SURFACE,
                              activebackground=BORDER, width=8,
                              relief="flat", bd=0, highlightthickness=0)
        self.log_box.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)
        self.log_box.tag_config("ok",   foreground=SUCCESS)
        self.log_box.tag_config("err",  foreground=ERROR)
        self.log_box.tag_config("info", foreground=TEXT)

    def _file_row(self, parent, var, cmd, lbl_attr, drop_handler=None):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1,
                         bd=0, highlightthickness=0)
        inner = tk.Frame(outer, bg=SURFACE, padx=14, pady=11,
                         bd=0, highlightthickness=0)
        inner.pack(fill="x")

        lbl = tk.Label(inner, text="Sleep bestand hier of kies…", bg=SURFACE, fg=MUTED,
                       font=("Helvetica Neue", 11), anchor="w", cursor="arrow")
        lbl.pack(side="left", fill="x", expand=True)
        setattr(self, lbl_attr, lbl)

        kies_cv = _rounded_btn(inner, "Kies…", cmd,
                               bg=SURFACE2, hv=BORDER, fg=TEXT,
                               font=("Helvetica Neue", 10), px=10, py=4, r=8, pbg=SURFACE)
        kies_cv.pack(side="right")

        # Drag-and-drop via native ObjC ctypes (_setup_native_dnd)
        return outer

    @staticmethod
    def _parse_drop(data):
        """Pad uit DnD event-data halen (macOS wikkelt paden met spaties in { })."""
        data = data.strip()
        if data.startswith("{") and data.endswith("}"):
            return data[1:-1]
        return data.split()[0]  # meerdere bestanden: eerste nemen

    def _log_direct(self, msg, tag="info"):
        """Log direct schrijven (geen root.after) — veilig vanuit DnD-callbacks."""
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _drop_pdf(self, event):
        p = self._parse_drop(event.data)
        self.pdf_path.set(p)
        self.pdf_lbl.config(text=Path(p).name, fg=TEXT)
        self._log_direct(f"PDF:  {Path(p).name}", "info")

    def _drop_ale(self, event):
        p = self._parse_drop(event.data)
        self.ale_path.set(p)
        self.ale_lbl.config(text=Path(p).name, fg=TEXT)
        self._log_direct(f"ALE:  {Path(p).name}", "info")

    def _pick_pdf(self):
        p = filedialog.askopenfilename(title="Kies PDF", filetypes=[("Alle bestanden","*.*")])
        if p:
            self.pdf_path.set(p)
            self.pdf_lbl.config(text=Path(p).name, fg=TEXT)
            self.log(f"PDF:  {Path(p).name}", "info")

    def _pick_ale(self):
        p = filedialog.askopenfilename(title="Kies ALE", filetypes=[("Alle bestanden","*.*")])
        if p:
            self.ale_path.set(p)
            self.ale_lbl.config(text=Path(p).name, fg=TEXT)
            self.log(f"ALE:  {Path(p).name}", "info")

    def _run(self):
        if not self._license_expiry:
            self.log("Geen geldige licentie. Activeer via Continuity Bridge → Licentie…", "err")
            return
        if not self.pdf_path.get():
            self.log("Kies eerst een PDF bestand.", "err"); return
        if not self.ale_path.get():
            self.log("Kies eerst een ALE bestand.", "err"); return
        self._btn_enabled = False
        self._draw_verwerk(SURFACE2, "Bezig…", MUTED)
        threading.Thread(target=self._process, daemon=True).start()

    def _process(self):
        try:
            clips  = parse_pdf(self.pdf_path.get(), self.log)
            result = process_ale(self.ale_path.get(), clips, self.log,
                                 write_rating=self.write_rating.get(),
                                 notes_col=self.notes_col.get())
            stem   = Path(self.ale_path.get()).stem
            out    = Path(self.ale_path.get()).parent / f"{stem}_updated_with_notes.ALE"
            result_bytes = result.encode("utf-8")
            try:
                out.write_bytes(result_bytes)
            except OSError:
                out = Path.home() / "Desktop" / f"{stem}_updated_with_notes.ALE"
                out.write_bytes(result_bytes)
            self.log(f"Klaar  —  {out.name} opgeslagen", "ok")
            os.system(f'open "{out.parent}"')
        except Exception as e:
            self.log(f"Fout: {e}", "err")
        finally:
            def _re_enable():
                self._btn_enabled = True
                self._draw_verwerk(AVID_B)
            self.root.after(0, _re_enable)

    def log(self, msg, tag="info"):
        def _do():
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n", tag)
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.root.after(0, _do)


def main():
    # Zet procesnaam vóór Tk-initialisatie zodat macOS-menubalk "Continuity Bridge" toont
    # ipv "Python". NSProcessInfo.setProcessName: moet vóór NSApplication/Tk-setup.
    try:
        import ctypes as _ct
        _lo = _ct.cdll.LoadLibrary('/usr/lib/libobjc.dylib')
        _lo.objc_getClass.restype    = _ct.c_void_p
        _lo.sel_registerName.restype = _ct.c_void_p
        _lo.objc_msgSend.restype     = _ct.c_void_p

        def _sel(n): return _lo.sel_registerName(n.encode())
        def _cls(n): return _lo.objc_getClass(n.encode())

        # NSString stringWithUTF8String:
        _lo.objc_msgSend.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_char_p]
        _name_ns = _lo.objc_msgSend(_cls('NSString'), _sel('stringWithUTF8String:'), b'Continuity Bridge')

        # [NSProcessInfo processInfo] setProcessName: name
        _lo.objc_msgSend.argtypes = [_ct.c_void_p, _ct.c_void_p]
        _procinfo = _lo.objc_msgSend(_cls('NSProcessInfo'), _sel('processInfo'))
        _lo.objc_msgSend.argtypes = [_ct.c_void_p, _ct.c_void_p, _ct.c_void_p]
        _lo.objc_msgSend(_procinfo, _sel('setProcessName:'), _name_ns)
    except Exception:
        pass

    # HAS_DND is altijd False (tkdnd2 incompatibel met Python 3.14)
    # Native ObjC ctypes DnD wordt opgezet in App.__init__ via _setup_native_dnd
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
