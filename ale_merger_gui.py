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

def parse_pdf(pdf_path, log, write_pu=True, write_afg=True):
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
                # "Comment:" staat vaak op eigen regel; volgende regels zijn de tekst
                general_note = ""
                _cm = re.search(r"Comment:\s*\n(.*?)(?=\n\s*\n|\Z)", text, re.DOTALL)
                if _cm:
                    _gn = _cm.group(1).strip().replace("\n", " ")
                    if _gn and not re.match(r"^\d+$", _gn):
                        general_note = _gn
                if not general_note:
                    _cm2 = re.search(r"Comment:\s+(.+)", text)
                    if _cm2:
                        _gn = _cm2.group(1).strip()
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
                    pending_is_pu  = False

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
                                                         "take_notes": pending_notes or general_note,
                                                         "page_note": general_note,
                                                         "is_pu": pending_is_pu}
                        if pending_clip_b:
                            if pending_clip_b not in clips:
                                clips[pending_clip_b] = {"circle": "", "scene": scene,
                                                         "description": description,
                                                         "take_notes": pending_notes or general_note,
                                                         "page_note": general_note,
                                                         "is_pu": pending_is_pu}

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
                        if re.match(r"^\d+(?:\s*[ms]\w*(?:\s+\d+\s*[ms]\w*)?)?$", notes, re.I):
                            notes = ""

                        pending_clip_a = (kaart_a + clip_a) if clip_a else None
                        pending_clip_b = (kaart_b + clip_b) if clip_b else None
                        pending_notes  = notes
                        pending_is_pu  = write_pu and _is_pu(take_num)

                    # Laatste take opslaan
                    if pending_clip_a:
                        if pending_clip_a not in clips:
                            clips[pending_clip_a] = {"circle": "", "scene": scene,
                                                     "description": description,
                                                     "take_notes": pending_notes or general_note,
                                                     "page_note": general_note,
                                                     "is_pu": pending_is_pu}
                    if pending_clip_b:
                        if pending_clip_b not in clips:
                            clips[pending_clip_b] = {"circle": "", "scene": scene,
                                                     "description": description,
                                                     "take_notes": pending_notes or general_note,
                                                     "page_note": general_note,
                                                     "is_pu": pending_is_pu}
                    pending_clip_a = pending_clip_b = pending_notes = None
                    pending_is_pu  = False
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

            # ── LVB / Millstreet format ────────────────────────────────────
            # Continuiteitsrapport met CARD Nr. + tabel TAKE/PU/CLIP#/RATING/AFG
            # Sterren in RATING-kolom zijn vector-curves (5-sterren systeem).
            # Twee cameras A en B; clips: A_XXXXCYYY + B_XXXXCYYY.
            # Algemene Sound Notes en Camera Notes gaan naar aparte kolommen.
            if "CONTINUITEITSRAPPORT" in text and "CARD Nr." in text and "CLIP #" in text:
                try:
                    tbls = page.find_tables()
                    if len(tbls) < 3:
                        continue

                    # ── Slate + Scene (tabel 0) ──
                    slate = ""
                    scene = ""
                    for row in tbls[0].extract():
                        if not row: continue
                        # Slate: numerieke waarde in kolom 7
                        if len(row) > 7 and row[7] and re.match(r'^\d{3,4}[A-Za-z]?$', (row[7] or "").strip()):
                            slate = row[7].strip()
                        # Scene: kolom 2, niet de koptekst of CARD-rij
                        if len(row) > 2 and row[2] and row[2] not in ("SCENE", "DATUM", "SCÈNE"):
                            val = row[2].strip()
                            if val and not re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', val) \
                                    and "CARD" not in val:
                                scene = val

                    if not slate:
                        continue

                    # ── Card nummers (alle tabellen, ook tabel 0) ──
                    card_a = ""
                    card_b = ""
                    for tbl in tbls:
                        for row in tbl.extract():
                            if not row: continue
                            row_str = " ".join(str(c or "") for c in row)
                            if "CARD" in row_str and "Nr" in row_str:
                                for cell in row:
                                    if not cell: continue
                                    cell = cell.strip()
                                    if re.match(r'^A\d+$', cell):
                                        card_a = cell[1:]   # "A19" → "19"
                                    elif re.match(r'^B\d+$', cell):
                                        card_b = cell[1:]   # "B17" → "17"
                                break
                        if card_a or card_b:
                            break

                    # ── Sound + Camera notes ──
                    sound_note = ""
                    camera_note = ""
                    for tbl in tbls:
                        ext = tbl.extract()
                        for ri, row in enumerate(ext):
                            if not row: continue
                            if "SOUND NOTES" in " ".join(str(c or "") for c in row):
                                # Verwerk alle rijen na de header tot de handtekening
                                for nr in ext[ri + 1:]:
                                    if not nr: continue
                                    sn = (nr[0] or "").strip()
                                    cn = (nr[1] or "").strip() if len(nr) > 1 else ""
                                    # Stop bij handtekening-rij
                                    if re.search(r'Script Supervisor|Assistant Director', sn + cn, re.I):
                                        break
                                    if sn:
                                        sound_note = (sound_note + " " + sn).strip()
                                    if cn:
                                        camera_note = (camera_note + " " + cn).strip()
                                break

                    # ── Take tabel ──
                    take_tbl = None
                    for tbl in tbls:
                        for row in tbl.extract()[:3]:
                            if row and any("TAKE" in str(c) for c in row if c) \
                                    and any("CLIP" in str(c) for c in row if c):
                                take_tbl = tbl
                                break
                        if take_tbl:
                            break

                    if take_tbl is None:
                        continue

                    take_extract = take_tbl.extract()

                    def _make_clip_key(letter, card_num, clip_num):
                        try:
                            return f"{letter}_{int(card_num):04d}C{int(clip_num):03d}"
                        except (ValueError, TypeError):
                            return None

                    for ri, row_data in enumerate(take_extract):
                        if ri == 0: continue          # header
                        if not row_data or not row_data[0]: continue
                        take_str = (row_data[0] or "").strip()
                        if not re.match(r'^\d+$', take_str): continue

                        clip_raw = re.sub(r'\s+', '', row_data[2] or "")
                        if not clip_raw or "?" in clip_raw:
                            continue

                        afg_val   = (row_data[5] or "").strip() if len(row_data) > 5 else ""
                        opmerking = (row_data[6] or "").strip() if len(row_data) > 6 else ""
                        circle    = ""
                        is_afg    = write_afg and "AFG" in afg_val.upper()

                        # ── Sterren tellen via vector-curves ──
                        star_count = 0
                        try:
                            row_cells = take_tbl.rows[ri].cells
                            if len(row_cells) > 4 and row_cells[4]:
                                rx0, rtop, rx1, rbottom = row_cells[4]
                                crop = page.crop((rx0, rtop, rx1, rbottom))
                                star_curves = [c for c in crop.curves
                                               if len(c.get('pts', [])) >= 10 and c.get('fill')]
                                star_count = len(star_curves)
                        except Exception:
                            pass

                        clip_info = {
                            "circle":       circle,
                            "scene":        scene,
                            "description":  "",
                            "take_notes":   opmerking,
                            "sound_notes":  sound_note,
                            "camera_notes": camera_note,
                            "stars":        str(star_count) if star_count > 0 else "",
                            "is_afg":       is_afg,
                        }

                        # ── Clip keys aanmaken ──
                        # Merge: notes/stars overschrijven bestaande lege waarden
                        def _lvb_set(key, info):
                            if not key: return
                            if key not in clips:
                                clips[key] = dict(info)
                            else:
                                ex = clips[key]
                                if info.get("take_notes") and not ex.get("take_notes"):
                                    ex["take_notes"] = info["take_notes"]
                                if info.get("stars") and (
                                        not ex.get("stars") or
                                        int(info["stars"]) > int(ex["stars"] or 0)):
                                    ex["stars"] = info["stars"]

                        if "/" in clip_raw:
                            m = re.match(r'C(\d+)/(\d+)', clip_raw)
                            if m:
                                a_num, b_num = m.group(1), m.group(2)
                                if card_a:
                                    _lvb_set(_make_clip_key("A", card_a, a_num), clip_info)
                                if card_b:
                                    _lvb_set(_make_clip_key("B", card_b, b_num), clip_info)
                        else:
                            m = re.match(r'C(\d+)', clip_raw)
                            if m:
                                num = m.group(1)
                                if card_a and not card_b:
                                    _lvb_set(_make_clip_key("A", card_a, num), clip_info)
                                elif card_b and not card_a:
                                    _lvb_set(_make_clip_key("B", card_b, num), clip_info)
                                else:
                                    # Eén clipnummer, beide cameras aanwezig:
                                    # "Alleen B" in opmerking → camera B; anders → camera A
                                    if re.search(r'\bAlleen\s+B\b', opmerking, re.I):
                                        if card_b:
                                            _lvb_set(_make_clip_key("B", card_b, num), clip_info)
                                    else:
                                        if card_a:
                                            _lvb_set(_make_clip_key("A", card_a, num), clip_info)

                except Exception as _e:
                    log(f"Fout bij LVB-pagina {page.page_number}: {_e}", "warn")
                continue  # LVB pagina verwerkt

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

def _cw_add(cw_dict, idx, val):
    """Voeg tekst toe aan col-write dict; zelfde idx → later samenvoegen met ' / '."""
    if idx is not None and val:
        v = str(val).replace("\n", " ").replace("\r", " ").strip()
        if v:
            cw_dict.setdefault(idx, []).append(v)


def process_ale(ale_path, clip_data, log, write_rating=True, notes_col="Auto", rating_col="Auto",
                sound_notes_col="Auto", camera_notes_col="Auto",
                pu_col="Auto", pu_position="voor",
                afg_col="Auto", afg_position="voor",
                general_notes_col="Auto"):
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

    name_idx  = idx("Name")
    tape_idx  = idx("Tape")
    scene_idx = idx("Scene")       # alleen bijwerken als al aanwezig
    desc_idx  = idx("Description") # alleen bijwerken als al aanwezig

    # Rating-kolom: gebruik keuze van gebruiker, anders auto-detectie
    if rating_col and rating_col != "Auto":
        rating_idx = idx(rating_col)
        if rating_idx is None:
            col_headers.append(rating_col)
            rating_idx = len(col_headers) - 1
            log(f"Kolom '{rating_col}' niet gevonden — toegevoegd aan ALE.", "info")
    else:
        rating_idx = next(
            (idx(c) for c in ("Rating", "Circle", "Score", "Stars")
             if idx(c) is not None),
            None
        )
        if rating_idx is None:
            col_headers.append("Rating")
            rating_idx = len(col_headers) - 1
            log("Geen rating-kolom gevonden — 'Rating' toegevoegd aan ALE.", "info")

    if rating_idx is not None:
        log(f"Rating → kolom '{col_headers[rating_idx]}'", "info")

    # Notes-kolom: gebruik keuze van gebruiker, anders auto-detectie
    take_notes_idx = None
    if notes_col not in ("Uit", ""):
        if notes_col and notes_col != "Auto":
            take_notes_idx = idx(notes_col)
            if take_notes_idx is None:
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
                col_headers.append("Comment")
                take_notes_idx = len(col_headers) - 1
                log("Geen notes-kolom gevonden — 'Comment' toegevoegd aan ALE.", "info")

    if take_notes_idx is not None:
        log(f"Notes → kolom '{col_headers[take_notes_idx]}'", "info")

    # LVB-kolommen: alleen toevoegen als er clip-data is met LVB-velden
    has_lvb = any(
        d.get("stars") or d.get("sound_notes") or d.get("camera_notes")
        for d in clip_data.values()
    )
    stars_idx = sound_idx = cam_idx = None
    if has_lvb:
        # Stars altijd toevoegen
        if "Stars" not in col_headers:
            col_headers.append("Stars")
            log("Kolom 'Stars' toegevoegd aan ALE (Sound Notes).", "info")
        stars_idx = col_headers.index("Stars")

        # Sound Notes kolom
        _sn_col = None if sound_notes_col in ("Uit", "") else (
            "Sound_Notes" if sound_notes_col in ("Auto", None) else sound_notes_col)
        if _sn_col:
            if _sn_col not in col_headers:
                col_headers.append(_sn_col)
                log(f"Kolom '{_sn_col}' toegevoegd aan ALE (Sound Notes).", "info")
            sound_idx = col_headers.index(_sn_col)

        # Camera Notes kolom
        _cn_col = None if camera_notes_col in ("Uit", "") else (
            "Camera_Notes" if camera_notes_col in ("Auto", None) else camera_notes_col)
        if _cn_col:
            if _cn_col not in col_headers:
                col_headers.append(_cn_col)
                log(f"Kolom '{_cn_col}' toegevoegd aan ALE (Camera Notes).", "info")
            cam_idx = col_headers.index(_cn_col)

    # PU-kolom: apart van has_lvb — PU kan ook in Haantjes/BFF-formaat voorkomen
    # Gebruik dezelfde kolom als take_notes_idx wanneer "Auto"
    pu_idx = None
    has_pu = any(d.get("is_pu") for d in clip_data.values())
    if has_pu:
        _pu_col_name = None if pu_col in ("Uit", "") else (
            None if pu_col in ("Auto", None) else pu_col)
        if _pu_col_name is None and pu_col not in ("Uit", ""):
            pu_idx = take_notes_idx
        elif _pu_col_name:
            if _pu_col_name not in col_headers:
                col_headers.append(_pu_col_name)
                log(f"Kolom '{_pu_col_name}' toegevoegd aan ALE (PU).", "info")
            pu_idx = col_headers.index(_pu_col_name)

    # AFG-kolom: zelfde logica als PU
    afg_idx = None
    has_afg = any(d.get("is_afg") for d in clip_data.values())
    if has_afg:
        _afg_col_name = None if afg_col in ("Uit", "") else (
            None if afg_col in ("Auto", None) else afg_col)
        if _afg_col_name is None and afg_col not in ("Uit", ""):
            afg_idx = take_notes_idx
        elif _afg_col_name:
            if _afg_col_name not in col_headers:
                col_headers.append(_afg_col_name)
                log(f"Kolom '{_afg_col_name}' toegevoegd aan ALE (AFG).", "info")
            afg_idx = col_headers.index(_afg_col_name)

    # Algemene opmerkingen-kolom (Haantjes Comment-veld onderaan pagina)
    gen_notes_idx = None
    has_gen = any(d.get("page_note") for d in clip_data.values())
    if has_gen and general_notes_col not in ("Uit", ""):
        _gn_col = "Camera_Notes" if general_notes_col in ("Auto", None) else general_notes_col
        if _gn_col not in col_headers:
            col_headers.append(_gn_col)
            log(f"Kolom '{_gn_col}' toegevoegd aan ALE (Algemene opmerkingen).", "info")
        gen_notes_idx = col_headers.index(_gn_col)

    # Alleen de kolommen die wij hebben toegevoegd krijgen een leeg veld per rij
    new_cols = col_headers[n_orig:]

    if name_idx is None:
        raise ValueError("Geen 'Name' kolom gevonden in ALE.")

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

        # LVB-formaat: ALE-naam "A_0019C001_260424_141158_p1CNK" → prefix "A_0019C001"
        if info is None:
            clip_name = parts[name_idx]
            for key in clip_data:
                if clip_name == key or clip_name.startswith(key + "_"):
                    info = clip_data[key]
                    break

        if info:
            matched += 1
            if write_rating and rating_idx is not None:
                if info.get("stars"):
                    parts[rating_idx] = info["stars"]   # LVB: cijfer 1-5
                elif info["circle"]:
                    parts[rating_idx] = info["circle"]  # andere formaten: V/X
            # Schrijf tekstvelden: zelfde kolom-idx → samenvoegen met " / "
            _cw = {}  # col_idx → [waarden]
            _cw_add(_cw, take_notes_idx, info.get("take_notes"))
            _cw_add(_cw, scene_idx,      info.get("scene"))
            _cw_add(_cw, desc_idx,       info.get("description"))
            _cw_add(_cw, sound_idx,      info.get("sound_notes"))
            _cw_add(_cw, cam_idx,        info.get("camera_notes"))
            _cw_add(_cw, gen_notes_idx,  info.get("page_note"))
            for _i, _vals in _cw.items():
                parts[_i] = " / ".join(_vals)
            # Stars (apart: numeriek, nooit samenvoegen)
            if stars_idx is not None and info.get("stars"):
                parts[stars_idx] = info["stars"]
            # PU-markering in kolom
            if info.get("is_pu") and pu_idx is not None:
                existing = parts[pu_idx].strip()
                if pu_position == "achter":
                    parts[pu_idx] = (existing + " (PU)").strip() if existing else "(PU)"
                else:
                    parts[pu_idx] = ("(PU) " + existing).strip() if existing else "(PU)"
            # AFG-markering in kolom
            if info.get("is_afg") and afg_idx is not None:
                existing = parts[afg_idx].strip()
                if afg_position == "achter":
                    parts[afg_idx] = (existing + " (AFG)").strip() if existing else "(AFG)"
                else:
                    parts[afg_idx] = ("(AFG) " + existing).strip() if existing else "(AFG)"
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

VERSION       = "1.2.1 (Beta)"
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


# Continuity Bridge kleurpallet — diep donker, elektrisch paars
BG       = "#060416"   # bijna-zwart met diepe paarse hint
SURFACE  = "#0C0A22"   # kaartachtergrond
SURFACE2 = "#161130"   # hover / actief
BORDER   = "#2E2060"   # subtiele paarse rand
TEXT     = "#F0ECFF"   # helder bijna-wit
MUTED    = "#6858AA"   # gedempte subtekst
AVID_B   = "#8B30F5"   # elektrisch paars (knop, header)
AVID_B_H = "#7A26E0"   # hover — iets donkerder
SUCCESS  = "#4ED98A"
ERROR    = "#FF5577"


def _rrect(cv, w, h, r, color, fg, text, font):
    """Teken afgerond rechthoek + tekst op canvas cv (smooth polygon, geen seams)."""
    cv.delete("all")
    r = min(r, w // 2, h // 2)
    pts = [
        r,   0,    w-r, 0,    w,   0,
        w,   r,    w,   h-r,  w,   h,
        w-r, h,    r,   h,    0,   h,
        0,   h-r,  0,   r,    0,   0,
    ]
    cv.create_polygon(pts, smooth=True, fill=color, outline=color)
    cv.create_text(w // 2, h // 2, text=text, fill=fg, font=font)


def _rrect_gradient(cv, w, h, r, c_tl, c_br, fg, text, font, darken=0.0):
    """Diagonaal kleurverloop (links-boven → rechts-onder), afgeronde hoeken."""
    import math
    cv.delete("all")
    r = min(r, w // 2, h // 2)

    def _parse(c):
        rv, gv, bv = int(c[1:3],16), int(c[3:5],16), int(c[5:7],16)
        f = 1.0 - darken
        return int(rv*f), int(gv*f), int(bv*f)

    r1, g1, b1 = _parse(c_tl)
    r2, g2, b2 = _parse(c_br)
    D = max(w + h * 0.5 - 1, 1)   # diagonaal bereik

    for y in range(h):
        if y < r:
            dy = r - y
            dx = int(math.sqrt(max(0.0, r*r - dy*dy)))
            x0, x1 = r - dx, w - r + dx
        elif y >= h - r:
            dy = y - (h - r)
            dx = int(math.sqrt(max(0.0, r*r - dy*dy)))
            x0, x1 = r - dx, w - r + dx
        else:
            x0, x1 = 0, w

        # Teken 4-pixel brede deelstrips voor diagonaal effect
        step = max(4, (x1 - x0) // 32)
        for sx in range(x0, x1, step):
            ex  = min(x1, sx + step + 1)
            t   = min(1.0, (sx + y * 0.5) / D)
            rc  = int(r1 + (r2 - r1) * t)
            gc  = int(g1 + (g2 - g1) * t)
            bc  = int(b1 + (b2 - b1) * t)
            cv.create_rectangle(sx, y, ex, y + 1,
                                fill=f"#{rc:02x}{gc:02x}{bc:02x}", outline="")

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


# ---------------------------------------------------------------------------
# VOORKEUREN  (opslaan in ~/.continuitybridge/prefs.json)
# ---------------------------------------------------------------------------
import json as _json_prefs

_PREFS_DIR  = Path.home() / ".continuitybridge"
_PREFS_FILE = _PREFS_DIR / "prefs.json"

_PREFS_DEFAULTS = {
    "write_rating":       False,
    "rating_col":         "Auto",
    "write_notes":        True,
    "notes_col":          "Auto",
    "write_sound_notes":  False,
    "sound_notes_col":    "Sound_Notes",
    "write_camera_notes": False,
    "camera_notes_col":   "Camera_Notes",
    "output_dir":         "",
    "output_suffix":      "_updated_with_notes",
    "rating_col_recent":  [],
    "notes_col_recent":   [],
    "write_pu_in_notes":  False,
    "write_afg_in_notes": False,
    "pu_col":             "Auto",
    "pu_position":        "voor",
    "afg_col":            "Auto",
    "afg_position":       "voor",
    "write_general_notes": False,
    "general_notes_col":  "Camera_Notes",
}
_INVALID_COL_VALUES = {"Kies kolom…", "Eigen naam…", "Kies kolom...", ""}

def _load_prefs():
    try:
        if _PREFS_FILE.exists():
            data = _json_prefs.loads(_PREFS_FILE.read_text("utf-8"))
            prefs = {**_PREFS_DEFAULTS, **data}
            # Sanitize: herstel placeholder-waarden naar Auto
            for key in ("rating_col", "notes_col"):
                if prefs[key] in _INVALID_COL_VALUES:
                    prefs[key] = "Auto"
            # Zorg dat recent-lijsten lists zijn
            for key in ("rating_col_recent", "notes_col_recent"):
                if not isinstance(prefs.get(key), list):
                    prefs[key] = []
            return prefs
    except Exception:
        pass
    return dict(_PREFS_DEFAULTS)

def _add_recent(prefs, key, value, max_items=3):
    """Voeg waarde toe aan recent-lijst, geen duplicaten, max max_items."""
    if not value or value == "Auto" or value in _INVALID_COL_VALUES:
        return
    lst = [v for v in prefs.get(key, []) if v != value]
    prefs[key] = [value] + lst[:max_items - 1]

def _save_prefs(prefs: dict):
    try:
        _PREFS_DIR.mkdir(parents=True, exist_ok=True)
        _PREFS_FILE.write_text(_json_prefs.dumps(prefs, indent=2), "utf-8")
    except Exception:
        pass


class App:
    # Meest voorkomende kolommen — gebruikt in hoofdscherm dropdown
    COMMON_COLS  = ["Comment", "Comments", "Description", "Label",
                    "Note", "Rating", "Stars", "Take_Notes"]

    NOTES_COLS   = ["Auto", "Comment", "Comments", "Description", "Label",
                    "Note", "Notes", "Take_Notes", "Take_notes"]
    RATING_COLS  = ["Auto", "Circled", "Rating", "Score", "Stars"]

    # Alle bekende Avid Media Composer kolomnamen, gegroepeerd
    AVID_COLS = {
        "Algemeen": [
            "Camera", "Camroll", "Color", "Comment", "Comments", "Creation Date",
            "Creator", "Date", "Description", "Drive", "Duration", "End", "Format",
            "Frame", "Label", "Lock", "Mark IN", "Mark OUT", "Marker", "Modified Date",
            "Note", "Offline", "Production", "Project", "Reel", "Reel #", "Scene",
            "Shoot Date", "Sound TC", "Soundroll", "Source File", "Start", "Take",
            "Take_Notes", "Tape", "TapeID", "Title", "Tracks", "Transfer", "Video",
        ],
        "Timecode": [
            "Aux TC 24", "Auxiliary TC1", "Auxiliary TC2", "Auxiliary TC3",
            "Auxiliary TC4", "Auxiliary TC5", "Film TC", "KN Dur", "KN End",
            "KN Film", "KN IN-OUT", "KN Mark IN", "KN Mark OUT", "KN Start",
            "Sound TC", "TC 24", "TC 25PD", "TC 30", "TC 30NP", "VITC",
        ],
        "Audio": [
            "Audio Bit Depth", "Audio File Format", "Audio SR",
            "Track Formats", "TRK1", "TRK2", "TRK3", "TRK4", "TRK5",
            "TRK6", "TRK7", "TRK8", "TRK9", "TRK10",
        ],
        "Video / Kleur": [
            "AFD", "ASC_SAT", "ASC_SOP", "Cadence", "CFPS", "Chroma Subsampling",
            "Color Bit Depth", "Color Space", "Color Transformation", "DPX",
            "Field Motion", "FPS", "Image Aspect Ratio", "Image Framing",
            "Image Size", "LUT", "Pixel Aspect Ratio", "Raster Dimension",
            "Reformat", "S3D Alignment", "S3D Channel", "S3D Clip Name",
            "S3D Contributors", "S3D Eye Order", "S3D Group Name",
            "S3D Inversion", "S3D InversionR", "S3D Leading Eye",
            "Video File Format", "UBITS",
        ],
        "Film / Ink": [
            "Auxiliary Ink", "AuxInk Dur", "AuxInk Edge", "AuxInk End",
            "AuxInk Film", "Frame Count Duration", "Frame Count End",
            "Frame Count Start", "IN-OUT", "Ink Dur", "Ink Edge", "Ink End",
            "Ink Film", "Ink Number", "KN Dur", "KN End", "KN Film",
            "KN IN-OUT", "KN Mark IN", "KN Mark OUT", "KN Start",
            "Labroll", "Master Dur", "Master Edge", "Master End",
            "Master Film", "Master Start", "Perf", "Pullin", "Pullout", "Slip",
        ],
        "Media / Proxy": [
            "Ancillary Data", "iDataLink", "Media File Path", "Media Status",
            "NEXIS Cache", "Proxy Offline", "Proxy Path", "Proxy Video",
            "Source Path", "UNC Path",
        ],
        "Rating / Status": [
            "Circled", "Rating", "Score", "Stars", "Status", "qc",
        ],
        "Vendor": [
            "Vendor Asset Description", "Vendor Asset ID", "Vendor Asset Keywords",
            "Vendor Asset Name", "Vendor Asset Price", "Vendor Asset Rights",
            "Vendor Asset Status", "Vendor Download Master", "Vendor Invoice ID",
            "Vendor Name", "Vendor Original Master",
        ],
        "Overig / Custom": [
            "CaptureGammaEquation", "Clip", "CreationDate", "Disc Description",
            "GammaForCDL", "hardware", "Index", "InitializedDate",
            "Journalist", "LensModelName", "Main Title 1(ASCII)",
            "Main Title 2(Multi Language)", "manufacturer", "MediaKind",
            "modelName", "MonitoringBaseCurve", "MonitoringDescription",
            "PDZK-MA2 CFPS", "Plug-In", "ProavIdRef", "Reel", "Reformat",
            "Sctk name", "serialNo", "software", "Soundfile", "T1", "T2",
            "T5", "T6", "T7", "T8", "Title 1(ASCII)", "Title 2(Multi Language)",
            "Transcription", "UserDiscId", "VFX", "VFX Reel",
        ],
    }

    def __init__(self, root):
        self.root = root
        self.ale_paths    = []   # lijst van ALE-bestandspaden
        self.pdf_paths    = []   # lijst van PDF-bestandspaden
        self._refresh_ale = lambda: None   # ingesteld door _multi_file_widget
        self._refresh_pdf = lambda: None

        # ── Voorkeuren laden ─────────────────────────────────────────────────
        _p = _load_prefs()
        self.write_rating     = tk.BooleanVar(value=_p["write_rating"])
        self.write_notes      = tk.BooleanVar(value=_p.get("write_notes", True))
        self.notes_col        = tk.StringVar(value=_p["notes_col"])
        self.rating_col       = tk.StringVar(value=_p["rating_col"])
        self.write_sound_notes  = tk.BooleanVar(value=_p["write_sound_notes"])
        self.sound_notes_col    = tk.StringVar(value=_p["sound_notes_col"])
        self.write_camera_notes = tk.BooleanVar(value=_p["write_camera_notes"])
        self.camera_notes_col   = tk.StringVar(value=_p["camera_notes_col"])
        self.output_dir       = tk.StringVar(value=_p["output_dir"])
        self.output_suffix    = tk.StringVar(value=_p.get("output_suffix", "_updated_with_notes"))
        self.write_pu_in_notes  = tk.BooleanVar(value=_p["write_pu_in_notes"])
        self.write_afg_in_notes = tk.BooleanVar(value=_p["write_afg_in_notes"])
        self.pu_col             = tk.StringVar(value=_p.get("pu_col", "Auto"))
        self.pu_position        = tk.StringVar(value=_p.get("pu_position", "voor"))
        self.afg_col            = tk.StringVar(value=_p.get("afg_col", "Auto"))
        self.afg_position       = tk.StringVar(value=_p.get("afg_position", "voor"))
        self.write_general_notes = tk.BooleanVar(value=_p.get("write_general_notes", False))
        self.general_notes_col  = tk.StringVar(value=_p.get("general_notes_col", "Camera_Notes"))
        self._prefs_cache = _p   # bewaar voor recents

        def _save_all():
            _save_prefs({
                "write_rating":       self.write_rating.get(),
                "rating_col":         self.rating_col.get(),
                "write_notes":        self.write_notes.get(),
                "notes_col":          self.notes_col.get(),
                "write_sound_notes":  self.write_sound_notes.get(),
                "sound_notes_col":    self.sound_notes_col.get(),
                "write_camera_notes": self.write_camera_notes.get(),
                "camera_notes_col":   self.camera_notes_col.get(),
                "output_dir":         self.output_dir.get(),
                "output_suffix":      self.output_suffix.get(),
                "rating_col_recent":  self._prefs_cache.get("rating_col_recent", []),
                "notes_col_recent":   self._prefs_cache.get("notes_col_recent", []),
                "write_pu_in_notes":  self.write_pu_in_notes.get(),
                "write_afg_in_notes": self.write_afg_in_notes.get(),
                "pu_col":             self.pu_col.get(),
                "pu_position":        self.pu_position.get(),
                "afg_col":            self.afg_col.get(),
                "afg_position":       self.afg_position.get(),
                "write_general_notes": self.write_general_notes.get(),
                "general_notes_col":  self.general_notes_col.get(),
            })
        self._save_prefs_all = _save_all

        # Sla prefs op bij elke wijziging (maar sla geen placeholders op)
        def _on_pref_change(*_):
            if self.rating_col.get() in _INVALID_COL_VALUES: return
            if self.notes_col.get()  in _INVALID_COL_VALUES: return
            _save_all()
        self.write_rating    .trace_add("write", _on_pref_change)
        self.write_notes     .trace_add("write", _on_pref_change)
        self.notes_col       .trace_add("write", _on_pref_change)
        self.rating_col      .trace_add("write", _on_pref_change)
        self.write_sound_notes .trace_add("write", _on_pref_change)
        self.sound_notes_col   .trace_add("write", _on_pref_change)
        self.write_camera_notes.trace_add("write", _on_pref_change)
        self.camera_notes_col  .trace_add("write", _on_pref_change)
        self.output_dir      .trace_add("write", _on_pref_change)
        self.output_suffix   .trace_add("write", _on_pref_change)
        self.write_pu_in_notes .trace_add("write", _on_pref_change)
        self.write_afg_in_notes.trace_add("write", _on_pref_change)
        self.pu_col            .trace_add("write", _on_pref_change)
        self.pu_position       .trace_add("write", _on_pref_change)
        self.afg_col           .trace_add("write", _on_pref_change)
        self.afg_position      .trace_add("write", _on_pref_change)
        self.write_general_notes.trace_add("write", _on_pref_change)
        self.general_notes_col .trace_add("write", _on_pref_change)
        self.root.title("Continuity Bridge")
        self.root.geometry("520x650")
        self.root.resizable(False, True)
        self.root.minsize(520, 520)
        self.root.configure(bg=BG)

        # ── Update-check ─────────────────────────────────────────────────────
        def _check_updates(silent=False):
            """Check GitHub releases. silent=True → alleen tonen bij nieuwere versie."""
            import urllib.request, json as _json2, ssl as _ssl
            def _do():
                try:
                    # SSL context: probeer systeemcerts, val terug op unverified
                    try:
                        _ctx = _ssl.create_default_context()
                    except Exception:
                        _ctx = _ssl._create_unverified_context()
                    req = urllib.request.Request(RELEASES_URL,
                          headers={"User-Agent": "ContinuityBridge"})
                    with urllib.request.urlopen(req, timeout=10, context=_ctx) as r:
                        releases = _json2.loads(r.read())
                    if not isinstance(releases, list) or not releases:
                        if not silent:
                            self.root.after(0, lambda: tk.messagebox.showinfo(
                                "Geen updates",
                                f"Je hebt de nieuwste versie ({VERSION})."))
                        return
                    data   = releases[0]
                    latest = data.get("tag_name", "").lstrip("v").strip()
                    if not latest:
                        return
                    def _vt(v):
                        nums = re.findall(r'\d+', v)
                        return tuple(int(x) for x in nums)
                    newer = _vt(latest) > _vt(VERSION)
                    if newer:
                        # Zoek het juiste asset op basis van platform/arch
                        import platform as _plat, sys as _sys2
                        assets = data.get("assets", [])
                        if _sys2.platform == 'win32':
                            want = 'ContinuityBridge.exe'
                        elif _plat.machine() == 'arm64':
                            want = 'ContinuityBridge-Silicon.dmg'
                        else:
                            want = 'ContinuityBridge-Intel.dmg'
                        asset = next((a for a in assets if a['name'] == want), None)
                        dl_url = asset['browser_download_url'] if asset else None
                        self.root.after(0, lambda lv=latest, url=dl_url:
                                        _show_update_dialog(lv, url))
                    elif not silent:
                        self.root.after(0, lambda: tk.messagebox.showinfo(
                            "Geen updates",
                            f"Je hebt de nieuwste versie ({VERSION})."))
                except Exception:
                    if not silent:
                        self.root.after(0, lambda: tk.messagebox.showinfo(
                            "Update-check",
                            "Kon de versie-info niet ophalen.\n"
                            "Controleer je internetverbinding of kijk op:\n"
                            f"github.com/{GITHUB_REPO}/releases"))
            threading.Thread(target=_do, daemon=True).start()

        def _show_update_dialog(latest_version, dl_url):
            """In-app update dialog met progress bar en automatische herstart."""
            import webbrowser as _wb
            dlg = tk.Toplevel(self.root)
            dlg.title("Update beschikbaar")
            dlg.configure(bg=BG)
            dlg.resizable(False, False)
            dlg.geometry("420x230")
            dlg.grab_set()

            tk.Label(dlg, text=f"Versie {latest_version} beschikbaar",
                     bg=BG, fg=TEXT, font=("Helvetica Neue", 14, "bold")).pack(pady=(24, 4))
            tk.Label(dlg, text=f"Jij hebt {VERSION}",
                     bg=BG, fg=MUTED, font=("Helvetica Neue", 11)).pack()

            prog_frame = tk.Frame(dlg, bg=BG)
            prog_frame.pack(fill="x", padx=36, pady=(18, 4))
            prog = ttk.Progressbar(prog_frame, length=348, mode='determinate')
            prog.pack()

            status_lbl = tk.Label(dlg, text="", bg=BG, fg=MUTED,
                                  font=("Helvetica Neue", 10))
            status_lbl.pack(pady=(0, 12))

            btn_frame = tk.Frame(dlg, bg=BG)
            btn_frame.pack()

            def _fallback():
                _wb.open(RELEASES_PAGE); dlg.destroy()

            def _start():
                if not dl_url:
                    _fallback(); return
                upd_cv.config(state="disabled")
                later_cv.config(state="disabled")
                threading.Thread(target=_download_and_install, daemon=True).start()

            def _download_and_install():
                import urllib.request as _ur2, tempfile, os, sys as _sys3, ssl as _ssl2
                try:
                    try:
                        _ctx2 = _ssl2.create_default_context()
                    except Exception:
                        _ctx2 = _ssl2._create_unverified_context()
                    # ── Download ──────────────────────────────────────────────
                    ext = '.exe' if _sys3.platform == 'win32' else '.dmg'
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    with _ur2.urlopen(dl_url, timeout=120, context=_ctx2) as resp:
                        total = int(resp.headers.get('Content-Length', 0))
                        done  = 0
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            tmp.write(chunk)
                            done += len(chunk)
                            if total:
                                dlg.after(0, lambda p=done/total*100: prog.config(value=p))
                            dlg.after(0, lambda d=done:
                                status_lbl.config(text=f"Downloaden… {d//1024} KB"))
                    tmp.close()
                    tmp_path = tmp.name

                    dlg.after(0, lambda: status_lbl.config(text="Installeren…"))

                    if _sys3.platform == 'win32':
                        import subprocess as _sp3
                        _sp3.Popen([tmp_path], shell=True)
                        dlg.after(0, _finish_win)
                    else:
                        import subprocess as _sp3, glob, shutil
                        # Mount DMG
                        r = _sp3.run(
                            ['hdiutil', 'attach', '-quiet', '-nobrowse',
                             '-noverify', tmp_path],
                            capture_output=True, text=True)
                        mount_pt = None
                        for line in r.stdout.strip().splitlines():
                            parts = line.split('\t')
                            if len(parts) >= 3 and '/Volumes/' in parts[-1]:
                                mount_pt = parts[-1].strip()
                        if not mount_pt:
                            raise RuntimeError("DMG mounten mislukt")
                        apps = glob.glob(os.path.join(mount_pt, '*.app'))
                        if not apps:
                            raise RuntimeError("Geen .app in DMG")
                        new_app = apps[0]

                        # Installeer — vervang huidige .app
                        if getattr(_sys3, 'frozen', False):
                            install_path = str(Path(_sys3.executable).parents[2])
                        else:
                            install_path = f"/Applications/{os.path.basename(new_app)}"

                        if os.path.exists(install_path):
                            shutil.rmtree(install_path)
                        shutil.copytree(new_app, install_path)
                        _sp3.run(['hdiutil', 'detach', '-quiet', mount_pt],
                                 capture_output=True)
                        os.unlink(tmp_path)
                        dlg.after(0, lambda ip=install_path: _finish_mac(ip))

                except Exception as exc:
                    dlg.after(0, lambda e=str(exc): _on_error(e))

            def _finish_mac(install_path):
                prog.config(value=100)
                status_lbl.config(fg=SUCCESS, text="Update klaar!")
                upd_cv.pack_forget()
                later_cv.pack_forget()
                rst = _rounded_btn(btn_frame, "🔄  Herstart app", lambda: _do_restart(install_path),
                                   bg=AVID_B, hv=AVID_B_H, fg="white",
                                   font=("Helvetica Neue", 11, "bold"),
                                   px=20, py=7, r=10, pbg=BG)
                rst.pack(side="left", padx=(0, 10))
                lat = _rounded_btn(btn_frame, "Later", dlg.destroy,
                                   bg=SURFACE2, hv=BORDER2, fg=MUTED,
                                   font=("Helvetica Neue", 11),
                                   px=16, py=7, r=10, pbg=BG)
                lat.pack(side="left")

            def _finish_win():
                prog.config(value=100)
                status_lbl.config(fg=SUCCESS, text="Installer gestart — volg de instructies.")
                later_cv.config(state="normal")

            def _do_restart(install_path):
                import subprocess as _sp4, sys as _sys4
                _sp4.Popen(['open', '-n', '-a', install_path])
                _sys4.exit(0)

            def _on_error(err):
                status_lbl.config(fg=ERROR, text=f"Fout: {err[:60]}")
                upd_cv.config(state="normal")
                later_cv.config(state="normal")

            upd_cv = _rounded_btn(btn_frame, "Update & Herstart", _start,
                                   bg=AVID_B, hv=AVID_B_H, fg="white",
                                   font=("Helvetica Neue", 11, "bold"),
                                   px=20, py=7, r=10, pbg=BG)
            upd_cv.pack(side="left", padx=(0, 10))
            later_cv = _rounded_btn(btn_frame, "Later", dlg.destroy,
                                    bg=SURFACE2, hv=BORDER2, fg=MUTED,
                                    font=("Helvetica Neue", 11),
                                    px=16, py=7, r=10, pbg=BG)
            later_cv.pack(side="left")

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
                # Server-side activatiecheck
                status_lbl.config(fg=MUTED, text="Activatie verifiëren…")
                _act_cv.config(state="disabled")
                def _do_server_check():
                    try:
                        import urllib.request as _ur, json as _js
                        payload = _js.dumps({
                            "serial":       serial_var.get().strip(),
                            "machine_uuid": _machine_uuid(),
                        }).encode()
                        req = _ur.Request(
                            "https://studiomichielboesveldt.nl/api/activate",
                            data=payload,
                            headers={"Content-Type": "application/json",
                                     "User-Agent": "ContinuityBridge"},
                            method="POST",
                        )
                        with _ur.urlopen(req, timeout=8) as r:
                            result = _js.loads(r.read())
                        server_ok     = result.get("ok", True)
                        server_reason = result.get("reason", "")
                    except Exception:
                        # Geen internet of server onbereikbaar → fail open
                        server_ok, server_reason = True, ""
                    def _finish():
                        _act_cv.config(state="normal")
                        if not server_ok and server_reason == "al_gebonden":
                            status_lbl.config(fg=ERROR,
                                text="✗ Serial al geactiveerd op een andere machine.\n"
                                     "Neem contact op met support@studiomichielboesveldt.nl")
                            return
                        _license_save(serial_var.get())
                        self._license_expiry = expiry
                        status_lbl.config(fg=SUCCESS,
                            text=f"✓ Welkom, {serial_name}!  {msg}")
                        dlg.after(1000, dlg.destroy)
                    dlg.after(0, _finish)
                threading.Thread(target=_do_server_check, daemon=True).start()

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

        # ── Verkochte licenties beheren ──────────────────────────────────────
        _MGR_TOKEN_FILE = _LIC_DIR / "mgr_token"
        _LICENSES_REPO  = "scprdytj2s-beep/cb-licenses"   # private repo

        def _mgr_token_load():
            try:
                return _MGR_TOKEN_FILE.read_text().strip()
            except Exception:
                return ""

        def _mgr_token_save(tok):
            _LIC_DIR.mkdir(parents=True, exist_ok=True)
            _MGR_TOKEN_FILE.write_text(tok.strip())

        def _fetch_licenses_from_github(token):
            """Haal data/licenses.json op uit private repo. Returns list of dicts."""
            import urllib.request as _ur
            url = (f"https://api.github.com/repos/{_LICENSES_REPO}"
                   f"/contents/data/licenses.json")
            req = _ur.Request(url, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "ContinuityBridge-Manager",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with _ur.urlopen(req, timeout=10) as r:
                data = _json.loads(r.read())
            import base64 as _b64m
            content = _b64m.b64decode(data["content"]).decode("utf-8")
            return _json.loads(content), data["sha"]

        def _revoke_serial_on_github(token, serial_clean):
            """Voeg serial toe aan revoked.json in publieke repo."""
            import urllib.request as _ur
            import base64 as _b64m
            rev_url = (f"https://api.github.com/repos/{GITHUB_REPO}"
                       f"/contents/revoked.json")
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "ContinuityBridge-Manager",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            }
            # Fetch bestaande revoked.json
            req = _ur.Request(rev_url, headers=headers)
            with _ur.urlopen(req, timeout=10) as r:
                existing = _json.loads(r.read())
            sha     = existing["sha"]
            revoked = _json.loads(_b64m.b64decode(existing["content"]))
            if serial_clean not in revoked:
                revoked.append(serial_clean)
            new_content = _b64m.b64encode(
                _json.dumps(revoked, indent=2).encode()).decode()
            body = _json.dumps({
                "message": f"revoke serial {serial_clean[:12]}…",
                "content": new_content,
                "sha":     sha,
            }).encode()
            put_req = _ur.Request(rev_url, data=body, headers=headers, method="PUT")
            with _ur.urlopen(put_req, timeout=10):
                pass

        def _show_license_manager():
            """Beheerdersvenster: toon alle verkochte licenties, intrekken mogelijk."""
            win = tk.Toplevel(self.root)
            win.title("Verkochte licenties")
            win.configure(bg=BG)
            win.geometry("860x540")
            win.grab_set(); win.lift(); win.focus_force()

            # Token-balk bovenaan
            hdr = tk.Frame(win, bg=SURFACE, pady=8, padx=14)
            hdr.pack(fill="x")
            tk.Label(hdr, text="GitHub manager token:", bg=SURFACE, fg=MUTED,
                     font=("Helvetica Neue", 11)).pack(side="left")
            tok_var = tk.StringVar(value=_mgr_token_load())
            tok_entry = tk.Entry(hdr, textvariable=tok_var, show="•", width=44,
                                 bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                                 relief="flat", font=("Menlo", 10), bd=4)
            tok_entry.pack(side="left", padx=(8, 6))
            _mgr_token_save_btn = tk.Button(hdr, text="Opslaan & laden",
                                            bg=AVID_B, fg="white",
                                            font=("Helvetica Neue", 10, "bold"),
                                            relief="flat", bd=0, cursor="hand2",
                                            padx=10, pady=4)
            hdr.pack(fill="x")

            # Status-label
            status_lbl = tk.Label(win, text="", bg=BG, fg=MUTED,
                                   font=("Helvetica Neue", 10))
            status_lbl.pack(anchor="w", padx=14, pady=(6, 2))

            # Tabel-frame
            tbl_frame = tk.Frame(win, bg=BG)
            tbl_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

            cols = ("naam", "email", "serial", "gekocht", "geldig_tm", "status")
            hdrs = ("Naam", "E-mail", "Serial", "Gekocht", "Geldig t/m", "Status")
            widths = (120, 180, 210, 80, 80, 70)

            style = ttk.Style()
            style.configure("Lic.Treeview",
                background=SURFACE, foreground=TEXT,
                fieldbackground=SURFACE, rowheight=24,
                font=("Helvetica Neue", 11))
            style.configure("Lic.Treeview.Heading",
                background=SURFACE2, foreground=MUTED,
                font=("Helvetica Neue", 10, "bold"))
            style.map("Lic.Treeview", background=[("selected", AVID_B)])

            vsb = tk.Scrollbar(tbl_frame, orient="vertical", bg=SURFACE2)
            tree = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                                 style="Lic.Treeview",
                                 yscrollcommand=vsb.set)
            vsb.config(command=tree.yview)
            for c, h, w in zip(cols, hdrs, widths):
                tree.heading(c, text=h)
                tree.column(c, width=w, minwidth=w, anchor="w")
            vsb.pack(side="right", fill="y")
            tree.pack(side="left", fill="both", expand=True)

            # Intrek-knop onderaan
            btn_row = tk.Frame(win, bg=BG)
            btn_row.pack(fill="x", padx=14, pady=(0, 12))
            revoke_btn = tk.Button(btn_row, text="⊘  Intrek geselecteerde licentie",
                                   bg=ERROR, fg="white",
                                   font=("Helvetica Neue", 11, "bold"),
                                   relief="flat", bd=0, cursor="hand2",
                                   padx=12, pady=6, state="disabled")
            revoke_btn.pack(side="left")
            count_lbl = tk.Label(btn_row, text="", bg=BG, fg=MUTED,
                                  font=("Helvetica Neue", 10))
            count_lbl.pack(side="right")

            _licenses_cache = []   # mutable closure list

            def _load_data():
                token = tok_var.get().strip()
                if not token:
                    status_lbl.config(text="Voer je GitHub manager token in.", fg=ERROR)
                    return
                _mgr_token_save(token)
                status_lbl.config(text="Laden…", fg=MUTED)
                revoke_btn.config(state="disabled")

                def _fetch():
                    try:
                        entries, _ = _fetch_licenses_from_github(token)
                        def _render():
                            tree.delete(*tree.get_children())
                            _licenses_cache.clear()
                            _licenses_cache.extend(entries)
                            today = _date.today()
                            for e in entries:
                                serial_clean = e.get("serial","").upper().replace(" ","")
                                # bepaal vervaldatum via serial-decode
                                try:
                                    _, expiry, _, _ = _serial_verify(e.get("serial",""))
                                    exp_str = expiry.strftime("%d-%m-%Y") if expiry else "?"
                                    if e.get("revoked"):
                                        status = "Ingetrokken"
                                    elif expiry and today >= expiry:
                                        status = "Verlopen"
                                    else:
                                        status = "Geldig"
                                except Exception:
                                    exp_str = "?"
                                    status  = "?"
                                gekocht = e.get("issuedAt","")[:10] if e.get("issuedAt") else "?"
                                tree.insert("", "end", values=(
                                    e.get("name",""),
                                    e.get("email",""),
                                    e.get("serial",""),
                                    gekocht,
                                    exp_str,
                                    status,
                                ))
                            count_lbl.config(text=f"{len(entries)} licentie(s)")
                            status_lbl.config(text="Geladen.", fg=SUCCESS)
                        self.root.after(0, _render)
                    except Exception as ex:
                        self.root.after(0, lambda: status_lbl.config(
                            text=f"Fout: {ex}", fg=ERROR))
                threading.Thread(target=_fetch, daemon=True).start()

            def _on_select(e):
                revoke_btn.config(
                    state="normal" if tree.selection() else "disabled")

            def _do_revoke():
                sel = tree.selection()
                if not sel: return
                vals = tree.item(sel[0])["values"]
                serial_str = vals[2]
                naam = vals[0]
                if not tk.messagebox.askyesno("Licentie intrekken",
                        f"Licentie van {naam} intrekken?\n\n"
                        f"{serial_str}\n\n"
                        "Dit kan niet ongedaan worden gemaakt."):
                    return
                token = tok_var.get().strip()
                status_lbl.config(text="Licentie intrekken…", fg=MUTED)
                serial_clean = serial_str.upper().replace(" ", "")

                def _revoke():
                    try:
                        _revoke_serial_on_github(token, serial_clean)
                        self.root.after(0, lambda: (
                            status_lbl.config(text=f"Ingetrokken: {serial_clean[:16]}…", fg=SUCCESS),
                            _load_data()
                        ))
                    except Exception as ex:
                        self.root.after(0, lambda: status_lbl.config(
                            text=f"Fout bij intrekken: {ex}", fg=ERROR))
                threading.Thread(target=_revoke, daemon=True).start()

            _mgr_token_save_btn.config(command=_load_data)
            _mgr_token_save_btn.pack(side="left", padx=(8, 6))
            tree.bind("<<TreeviewSelect>>", _on_select)
            revoke_btn.config(command=_do_revoke)

            # Auto-laden als token al opgeslagen is
            if tok_var.get().strip():
                win.after(200, _load_data)

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
            _appmenu.add_separator()
            _appmenu.add_command(label='Voorkeuren…', command=self._show_prefs,
                                 accelerator='Command+,')
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
            self.root.createcommand('tk::mac::ShowPreferences', self._show_prefs)
        except Exception:
            pass

        self.root.bind_all('<Command-comma>', lambda e: self._show_prefs())

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

    def _pick_column(self, var, parent_win=None):
        """Zoekbaar keuzevenster met alle bekende Avid-kolomnamen."""
        _prev_val = var.get()
        anchor = parent_win or self.root

        dlg = tk.Toplevel(anchor)
        dlg.title("Kies kolom")
        dlg.resizable(False, False)
        dlg.configure(bg=BG)
        dlg.grab_set()

        def _cancel():
            var.set(_prev_val)
            dlg.destroy()
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

        # Platte gesorteerde lijst per groep, met groepslabels
        all_items = []
        for grp, cols in App.AVID_COLS.items():
            all_items.append((f"── {grp} ──", True, ""))
            for c in sorted(set(cols)):
                all_items.append((c, False, c))

        # Zoekbalk
        tk.Label(dlg, text="Zoek:", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(anchor="w", padx=16, pady=(14, 4))
        search_var = tk.StringVar()
        ent = tk.Entry(dlg, textvariable=search_var, width=30,
                       bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                       relief="flat", font=("Helvetica Neue", 12),
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=AVID_B)
        ent.pack(padx=16, ipady=4, fill="x")
        ent.focus_set()

        # Listbox + scrollbar
        frame_lb = tk.Frame(dlg, bg=BORDER, bd=1, relief="flat")
        frame_lb.pack(padx=16, pady=8, fill="both", expand=True)
        sb = tk.Scrollbar(frame_lb, orient="vertical", bg=SURFACE2,
                          troughcolor=SURFACE, relief="flat", bd=0)
        lb = tk.Listbox(frame_lb, yscrollcommand=sb.set,
                        bg=SURFACE, fg=TEXT, selectbackground=AVID_B,
                        selectforeground="white", relief="flat", bd=0,
                        font=("Helvetica Neue", 11), activestyle="none",
                        height=16, width=32)
        sb.config(command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)

        _lb_map = []

        def _fill(filter_text=""):
            lb.delete(0, "end")
            _lb_map.clear()
            q = filter_text.strip().lower()
            for label, is_hdr, col in all_items:
                if q:
                    if is_hdr: continue
                    if q not in col.lower(): continue
                lb.insert("end", f"  {label}" if not is_hdr else label)
                if is_hdr:
                    lb.itemconfig("end", fg=MUTED, selectbackground=SURFACE,
                                  selectforeground=MUTED)
                _lb_map.append(None if is_hdr else col)

        _fill()
        search_var.trace_add("write", lambda *_: _fill(search_var.get()))

        # Eigen naam onderaan
        tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=16)
        own_frame = tk.Frame(dlg, bg=BG)
        own_frame.pack(fill="x", padx=16, pady=8)
        tk.Label(own_frame, text="Of typ eigen naam:", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 10)).pack(side="left")
        own_var = tk.StringVar()
        own_ent = tk.Entry(own_frame, textvariable=own_var, width=18,
                           bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                           relief="flat", font=("Helvetica Neue", 11),
                           highlightthickness=1, highlightbackground=BORDER,
                           highlightcolor=AVID_B)
        own_ent.pack(side="left", padx=(8, 0), ipady=3)

        def _confirm(col_name=None):
            name = col_name or own_var.get().strip()
            if name:
                var.set(name)
            dlg.destroy()

        lb.bind("<Double-Button-1>", lambda e: _confirm(
            _lb_map[lb.curselection()[0]] if lb.curselection() and _lb_map[lb.curselection()[0]] else None))
        ent.bind("<Return>", lambda e: _confirm(
            _lb_map[lb.curselection()[0]] if lb.curselection() and _lb_map[lb.curselection()[0]] else None)
            or (own_var.get().strip() and _confirm()))
        own_ent.bind("<Return>", lambda e: _confirm())

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(anchor="e", padx=16, pady=(0, 14))
        _rounded_btn(btn_row, "Annuleer", _cancel,
                     bg=SURFACE2, hv=SURFACE, fg=TEXT,
                     font=("Helvetica Neue", 11), px=16, py=6, r=8, pbg=BG).pack(side="left", padx=(0, 8))
        _rounded_btn(btn_row, "Kies", lambda: _confirm(
                         _lb_map[lb.curselection()[0]] if lb.curselection() and _lb_map[lb.curselection()[0]] else None),
                     bg=AVID_B, hv="#2a6fbd", fg="white",
                     font=("Helvetica Neue", 11, "bold"), px=16, py=6, r=8, pbg=BG).pack(side="left")

        dlg.update_idletasks()
        cx = anchor.winfo_x() + anchor.winfo_width()  // 2
        cy = anchor.winfo_y() + anchor.winfo_height() // 2
        dlg.geometry(f"+{cx - dlg.winfo_width()//2}+{cy - dlg.winfo_height()//2}")
        dlg.wait_window()

    def _show_prefs(self):
        """Voorkeuren-venster (modaal)."""
        win = tk.Toplevel(self.root)
        win.title("Voorkeuren")
        win.resizable(False, False)
        win.configure(bg=BG)
        win.grab_set()

        PAD = 20
        ROW = 32

        # ── Titel ──────────────────────────────────────────────────────────
        tk.Label(win, text="Voorkeuren", bg=BG, fg=TEXT,
                 font=("Helvetica Neue", 15, "bold")).pack(anchor="w", padx=PAD, pady=(PAD, 14))

        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=PAD)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="x", padx=PAD, pady=(14, 6))

        def _section_hdr(parent, label):
            f = tk.Frame(parent, bg=BG)
            f.pack(fill="x", pady=(10, 2))
            tk.Label(f, text=label, bg=BG, fg=AVID_B,
                     font=("Helvetica Neue", 9, "bold")).pack(side="left")
            tk.Frame(f, bg=BORDER, height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0), pady=(1, 0))

        def _row(label):
            f = tk.Frame(body, bg=BG, height=ROW)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=label, bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 11), width=18, anchor="w").pack(side="left")
            return f

        # Stijl voor alle comboboxen in dit venster
        style = ttk.Style()
        CUSTOM = "Kies kolom…"

        def _cb(parent, var, values):
            all_values = list(values) + [CUSTOM]
            cb = ttk.Combobox(parent, textvariable=var, values=all_values,
                              state="readonly", width=16,
                              style="CB.TCombobox", font=("Helvetica Neue", 11))
            cb.pack(side="left")
            def _on_select(e):
                if var.get() == CUSTOM:
                    self._pick_column(var, win)
            cb.bind("<<ComboboxSelected>>", _on_select)
            return cb

        _section_hdr(body, "PER TAKE")

        # Notes: checkbox + "→" + kolom-dropdown
        r2 = _row("Notes")
        tk.Checkbutton(r2, variable=self.write_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r2, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb(r2, self.notes_col, self.NOTES_COLS)

        # Rating: checkbox + "→" + kolom-dropdown
        r1 = _row("Rating")
        tk.Checkbutton(r1, variable=self.write_rating,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r1, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb(r1, self.rating_col, self.RATING_COLS)

        # PU: checkbox + "→" + kolom-dropdown + voor/achter
        PU_COLS = ["Auto", "Comment", "Comments", "Notes", "Take_Notes"]
        r5 = _row("Schrijf (PU)")
        tk.Checkbutton(r5, variable=self.write_pu_in_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r5, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb(r5, self.pu_col, PU_COLS)
        tk.Label(r5, text="positie:", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 10)).pack(side="left", padx=(8, 4))
        ttk.Combobox(r5, textvariable=self.pu_position,
                     values=["voor", "achter"], state="readonly", width=7,
                     style="CB.TCombobox",
                     font=("Helvetica Neue", 11)).pack(side="left")

        # AFG: checkbox + "→" + kolom-dropdown + voor/achter
        AFG_COLS = ["Auto", "Comment", "Comments", "Notes", "Take_Notes"]
        r6 = _row("Schrijf (AFG)")
        tk.Checkbutton(r6, variable=self.write_afg_in_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r6, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb(r6, self.afg_col, AFG_COLS)
        tk.Label(r6, text="positie:", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 10)).pack(side="left", padx=(8, 4))
        ttk.Combobox(r6, textvariable=self.afg_position,
                     values=["voor", "achter"], state="readonly", width=7,
                     style="CB.TCombobox",
                     font=("Helvetica Neue", 11)).pack(side="left")

        body2 = tk.Frame(win, bg=BG)
        body2.pack(fill="x", padx=PAD)

        def _row2(label):
            f = tk.Frame(body2, bg=BG, height=ROW)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=label, bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 11), width=18, anchor="w").pack(side="left")
            return f

        SOUND_COLS  = ["Sound_Notes", "Sound", "Audio_Notes"]
        CAMERA_COLS = ["Camera_Notes", "Continuity_Notes", "Script_Notes"]
        GEN_COLS    = ["Camera_Notes", "Opmerkingen", "Continuity_Notes", "Script_Notes"]

        def _cb2(parent, var, values):
            CUSTOM = "Kies kolom…"
            cb = ttk.Combobox(parent, textvariable=var, values=list(values) + [CUSTOM],
                              state="readonly", width=16,
                              style="CB.TCombobox", font=("Helvetica Neue", 11))
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>",
                    lambda e: self._pick_column(var, win) if var.get() == CUSTOM else None)
            return cb

        _section_hdr(body2, "ALGEMENE OPMERKINGEN PER SLATE")

        r7 = _row2("Sound Notes")
        tk.Checkbutton(r7, variable=self.write_sound_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r7, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb2(r7, self.sound_notes_col, SOUND_COLS)

        r8 = _row2("Camera Notes")
        tk.Checkbutton(r8, variable=self.write_camera_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r8, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb2(r8, self.camera_notes_col, CAMERA_COLS)

        r9 = _row2("Opmerkingen")
        tk.Checkbutton(r9, variable=self.write_general_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=("Helvetica Neue", 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r9, text="→", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11)).pack(side="left", padx=(4, 6))
        _cb2(r9, self.general_notes_col, GEN_COLS)

        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=PAD, pady=(12, 0))

        # Uitvoermap — helemaal onderaan
        body3 = tk.Frame(win, bg=BG)
        body3.pack(fill="x", padx=PAD, pady=(8, 0))

        r4 = tk.Frame(body3, bg=BG, height=ROW)
        r4.pack(fill="x", pady=4)
        tk.Label(r4, text="Uitvoermap", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11), width=18, anchor="w").pack(side="left")
        out_entry = tk.Entry(r4, textvariable=self.output_dir, width=22,
                             bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                             relief="flat", font=("Helvetica Neue", 11),
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=AVID_B)
        out_entry.pack(side="left", ipady=3)

        def _pick_dir():
            d = filedialog.askdirectory(title="Kies uitvoermap",
                                        initialdir=self.output_dir.get() or Path.home())
            if d:
                self.output_dir.set(d)
        _rounded_btn(r4, "Kies…", _pick_dir,
                     bg=SURFACE2, hv=BORDER, fg=TEXT,
                     font=("Helvetica Neue", 11), px=10, py=3, r=6,
                     pbg=BG).pack(side="left", padx=(4, 0))
        tk.Label(r4, text="(leeg = zelfde map als ALE)", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 10)).pack(side="left", padx=(8, 0))

        r4b = tk.Frame(body3, bg=BG, height=ROW)
        r4b.pack(fill="x", pady=4)
        tk.Label(r4b, text="Bestandsnaam", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 11), width=18, anchor="w").pack(side="left")
        tk.Label(r4b, text="{originele naam}", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 10)).pack(side="left")
        tk.Entry(r4b, textvariable=self.output_suffix, width=20,
                 bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Helvetica Neue", 11),
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=AVID_B).pack(side="left", ipady=3, padx=(4, 0))
        tk.Label(r4b, text=".ALE", bg=BG, fg=MUTED,
                 font=("Helvetica Neue", 10)).pack(side="left", padx=(4, 0))

        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=PAD, pady=(8, 0))

        # Sluit-knop
        btn = _rounded_btn(win, "Sluit", win.destroy,
                           bg=AVID_B, hv="#2a6fbd", fg="white",
                           font=("Helvetica Neue", 12, "bold"),
                           px=24, py=8, r=10, pbg=BG)
        btn.pack(anchor="e", padx=PAD, pady=PAD)

        win.update_idletasks()
        # Centreer op hoofdvenster
        mw = self.root.winfo_x() + self.root.winfo_width()  // 2
        mh = self.root.winfo_y() + self.root.winfo_height() // 2
        w, h = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{mw - w//2}+{mh - h//2}")
        win.wait_window()

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
            ale_added = pdf_added = False
            _first = True
            try:
                while True:
                    filepath = _drop_queue.get_nowait()
                    # Sluit open dropdown bij eerste bestand in deze batch
                    if _first:
                        _first = False
                        try:
                            app_ref.root.focus_force()
                            app_ref.root.event_generate('<Button-1>', x=0, y=0)
                        except Exception:
                            pass
                    p = Path(filepath)
                    ext = p.suffix.lower()
                    if ext == ".pdf":
                        if filepath not in app_ref.pdf_paths:
                            app_ref.pdf_paths.append(filepath)
                            app_ref._log_direct(f"PDF:  {p.name}", "info")
                            pdf_added = True
                    elif ext in (".ale", ".txt"):
                        if filepath not in app_ref.ale_paths:
                            app_ref.ale_paths.append(filepath)
                            app_ref._log_direct(f"ALE:  {p.name}", "info")
                            ale_added = True
                    else:
                        app_ref._log_direct(f"Onbekend bestandstype: {p.name}", "info")
            except _queue.Empty:
                pass
            if ale_added:
                app_ref._refresh_ale()
            if pdf_added:
                app_ref._refresh_pdf()
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
                        for f in files:
                            # Alleen queue-put — GEEN root.after() vanuit ctypes-context
                            # (Python 3.14: PyEval_RestoreThread(NULL) = fatal crash)
                            _drop_queue.put(f)
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
        _HDR_H  = 56
        _GL     = (0xA0, 0x30, 0xFF)   # links: fel elektrisch violet
        _GR     = (0x50, 0x10, 0xC0)   # rechts: levendig indigo (niet zwart)

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

        # Sectielabels met genummerd badge
        def _section_label(parent, number, text):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", pady=(0, 7))
            # Badge: klein paars vierkantje met nummer
            badge = tk.Canvas(row, width=18, height=18, bg=BG,
                              bd=0, highlightthickness=0)
            badge.pack(side="left", padx=(0, 8))
            badge.create_rectangle(0, 0, 18, 18, fill=AVID_B, outline="")
            badge.create_text(9, 9, text=str(number), fill="white",
                              font=("Helvetica Neue", 9, "bold"))
            tk.Label(row, text=text.upper(), bg=BG, fg=MUTED,
                     font=("Helvetica Neue", 9, "bold"), anchor="w").pack(side="left")

        _section_label(body, 1, "Avid Log Exchange file (ALE)")
        self._multi_file_widget(body, self.ale_paths, "ALE").pack(fill="x", pady=(0, 14))

        _section_label(body, 2, "Continuïteitsrapport (PDF)")
        self._multi_file_widget(body, self.pdf_paths, "PDF").pack(fill="x", pady=(0, 14))

        # ── Notes-kolom keuze ─────────────────────────────────────────────────
        _section_label(body, 3, "Notes → kolom")

        opts = tk.Frame(body, bg=BG)
        opts.pack(fill="x", pady=(0, 0))

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

        self.root.option_add("*TCombobox*Listbox.background",       SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground",       TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", AVID_B)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font",             "{{Helvetica Neue} 11}")
        self.root.option_add("*TCombobox*Listbox.relief",           "flat")
        self.root.option_add("*TCombobox*Listbox.borderWidth",      "0")

        PICK = "Kies kolom…"

        def _make_col_values(recent_key):
            base    = self.COMMON_COLS
            recents = [r for r in self._prefs_cache.get(recent_key, [])
                       if r not in base and r != "Auto"]
            return ["Auto"] + base + recents + [PICK]

        def _main_cb(parent, var, recent_key, width):
            cb = ttk.Combobox(parent, textvariable=var,
                              values=_make_col_values(recent_key),
                              state="readonly", width=width,
                              style="CB.TCombobox", font=("Helvetica Neue", 11))
            cb.pack(side="left", fill="x", expand=True)
            def _on_select(e):
                if var.get() == PICK:
                    prev = self._prefs_cache.get(recent_key.replace("_recent", ""), "Auto") or "Auto"
                    var.set(prev)
                    self._pick_column(var)
                    _add_recent(self._prefs_cache, recent_key, var.get())
                    self._save_prefs_all()
                    cb.config(values=_make_col_values(recent_key))
                else:
                    _add_recent(self._prefs_cache, recent_key, var.get())
                    self._save_prefs_all()
                    cb.config(values=_make_col_values(recent_key))
            cb.bind("<<ComboboxSelected>>", _on_select)
            return cb

        # Dropdown gewrapped in border-frame (zelfde look als file rows)
        notes_outer = tk.Frame(opts, bg=BORDER, padx=1, pady=1,
                               bd=0, highlightthickness=0)
        notes_outer.pack(fill="x", expand=True)
        notes_inner = tk.Frame(notes_outer, bg=SURFACE, padx=10, pady=8,
                               bd=0, highlightthickness=0)
        notes_inner.pack(fill="x")

        cb_notes = _main_cb(notes_inner, self.notes_col, "notes_col_recent", width=30)

        # ── Voorkeuren-hint + Wis-knop ────────────────────────────────────────
        hint_row = tk.Frame(body, bg=BG)
        hint_row.pack(fill="x", pady=(12, 12))

        hint_lbl = tk.Label(hint_row,
                            text="⚙  Meer instellingen in Voorkeuren  (⌘,)",
                            bg=BG, fg=MUTED,
                            font=("Helvetica Neue", 10), cursor="arrow", anchor="w")
        hint_lbl.pack(side="left", fill="x", expand=True)
        hint_lbl.bind("<Button-1>", lambda e: self._show_prefs())
        hint_lbl.bind("<Enter>",    lambda e: hint_lbl.config(fg=TEXT))
        hint_lbl.bind("<Leave>",    lambda e: hint_lbl.config(fg=MUTED))

        def _clear_all():
            self.ale_paths.clear()
            self.pdf_paths.clear()
            self._refresh_ale()
            self._refresh_pdf()
            # Log leegmaken
            self.log_box.config(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.config(state="disabled")

        clear_cv = _rounded_btn(hint_row, "↺  Wis alles", _clear_all,
                                bg=SURFACE2, hv=BORDER, fg=MUTED,
                                font=("Helvetica Neue", 10), px=10, py=3, r=8, pbg=BG)
        clear_cv.pack(side="right")

        # ── Verwerk-knop (afgeronde Canvas, full-width) ──────────────────────
        _VF = ("Helvetica Neue", 14, "bold")
        _VH = 48   # hoogte
        _VR = 12   # hoek-radius
        self._btn_enabled = True
        self.btn = tk.Canvas(body, height=_VH, bd=0, highlightthickness=0, bg=BG, cursor="arrow")
        self.btn.pack(fill="x")

        _BTN_TL = "#B040FF"   # diagonaal links-boven: fel violet
        _BTN_BR = "#5814C0"   # diagonaal rechts-onder: diep paars

        def _draw_verwerk(label="✦  Verwerk", darken=0.0, disabled=False):
            w = self.btn.winfo_width()
            if w < 2: return
            if disabled:
                _rrect(self.btn, w, _VH, _VR, SURFACE2, MUTED, label, _VF)
            else:
                _rrect_gradient(self.btn, w, _VH, _VR,
                                _BTN_TL, _BTN_BR, "#FFFFFF", label, _VF,
                                darken=darken)

        def _on_verwerk_resize(e):
            if self._btn_enabled: _draw_verwerk()
            else:                 _draw_verwerk("Bezig…", disabled=True)

        self.btn.bind("<Configure>", _on_verwerk_resize)

        def _btn_enter(e):
            if self._btn_enabled: _draw_verwerk(darken=0.12)
        def _btn_leave(e):
            if self._btn_enabled: _draw_verwerk()
        def _btn_press(e):
            if self._btn_enabled: _draw_verwerk(darken=0.25)
        def _btn_click(e):
            if self._btn_enabled: self._run()

        self.btn.bind("<Enter>",           _btn_enter)
        self.btn.bind("<Leave>",           _btn_leave)
        self.btn.bind("<ButtonPress-1>",   _btn_press)
        self.btn.bind("<ButtonRelease-1>", lambda e: _btn_leave(e))
        self.btn.bind("<Button-1>",        _btn_click)

        # Sla _draw_verwerk op voor gebruik in _process
        self._draw_verwerk = _draw_verwerk

        # ── Log ──────────────────────────────────────────────────────────────
        log_outer = tk.Frame(self.root, bg=BORDER, padx=1, pady=1,
                             bd=0, highlightthickness=0)
        log_outer.pack(fill="both", expand=True, padx=22, pady=(10, 18))

        # Groene accentlijn links (zoals in referentieplaatje)
        tk.Frame(log_outer, bg=SUCCESS, width=3).pack(side="left", fill="y")

        log_frame = tk.Frame(log_outer, bg=SURFACE, bd=0, highlightthickness=0)
        log_frame.pack(fill="both", expand=True)

        self.log_box = tk.Text(log_frame, bg=SURFACE, fg=MUTED,
            font=("Menlo", 10), relief="flat", bd=0, highlightthickness=0,
            padx=14, pady=12, wrap="word", state="disabled", height=5,
            cursor="arrow")

        # Dunne canvas-scrollbar (macOS negeert bg/troughcolor op native Scrollbar)
        _SB_W = 6
        log_sb_cv = tk.Canvas(log_frame, width=_SB_W, bg=SURFACE,
                              bd=0, highlightthickness=0)
        _thumb = log_sb_cv.create_rectangle(0, 0, _SB_W, 30,
                                            fill=BORDER, outline="", tags="thumb")
        def _sb_set(first, last):
            first, last = float(first), float(last)
            h = log_sb_cv.winfo_height() or 100
            y0, y1 = int(first * h), int(last * h)
            if y1 - y0 < 16: y1 = y0 + 16
            y1 = min(y1, h)
            log_sb_cv.coords(_thumb, 1, y0, _SB_W - 1, y1)
            log_sb_cv.itemconfig(_thumb,
                fill=MUTED if (last - first) < 0.999 else SURFACE)
        def _sb_click(e):
            h = log_sb_cv.winfo_height() or 100
            self.log_box.yview("moveto", e.y / h)
        log_sb_cv.bind("<Button-1>", _sb_click)
        log_sb_cv.bind("<B1-Motion>", _sb_click)
        self.log_box.configure(yscrollcommand=_sb_set)
        log_sb_cv.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)
        self.log_box.tag_config("ok",   foreground=SUCCESS)
        self.log_box.tag_config("err",  foreground=ERROR)
        self.log_box.tag_config("info", foreground=TEXT)

    @staticmethod
    def _draw_file_icon(parent, ext, color, fold_color):
        """Canvas-bestandsicoontje (document met gevouwen hoek)."""
        W, H, FOLD = 34, 40, 10
        cv = tk.Canvas(parent, width=W, height=H, bg=SURFACE,
                       bd=0, highlightthickness=0)
        # Document-body
        cv.create_polygon(
            [0, 0,  W-FOLD, 0,  W, FOLD,  W, H,  0, H],
            fill=color, outline=""
        )
        # Gevouwen hoekje
        cv.create_polygon(
            [W-FOLD, 0,  W-FOLD, FOLD,  W, FOLD],
            fill=fold_color, outline=""
        )
        # Extensietekst
        cv.create_text(W//2, H//2 + 3, text=ext,
                       fill="white", font=("Helvetica Neue", 8, "bold"))
        return cv

    def _multi_file_widget(self, parent, paths_list, file_type):
        """Multi-bestandswidget: scrollbare lijst + × per rij + Kies-knop."""
        _ROW_H = 38     # hoogte per bestandsrij (px)
        _MAX_V = 2      # max zichtbare rijen zonder scrollen

        badge_color = "#8B30F5" if file_type == "ALE" else "#E8402A"

        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1, bd=0, highlightthickness=0)
        inner = tk.Frame(outer, bg=SURFACE, bd=0, highlightthickness=0)
        inner.pack(fill="x")

        # ── Scrollbare lijst (hoogte dynamisch) ───────────────────────────
        list_host = tk.Frame(inner, bg=SURFACE)
        # list_host wordt pas gepacked zodra er bestanden zijn

        list_cv = tk.Canvas(list_host, bg=SURFACE, bd=0, highlightthickness=0,
                            height=_ROW_H)
        list_frame = tk.Frame(list_cv, bg=SURFACE)
        list_sb = tk.Scrollbar(list_host, orient="vertical", command=list_cv.yview,
                               bg=SURFACE2, troughcolor=SURFACE, width=8,
                               relief="flat", bd=0, highlightthickness=0)
        list_cv.configure(yscrollcommand=list_sb.set)
        _lwin = list_cv.create_window((0, 0), window=list_frame, anchor="nw")

        list_frame.bind("<Configure>",
                        lambda e: list_cv.configure(scrollregion=list_cv.bbox("all")))
        list_cv.bind("<Configure>",
                     lambda e: list_cv.itemconfig(_lwin, width=e.width))

        # ── Statusbalk (altijd zichtbaar) ────────────────────────────────
        sep_line  = tk.Frame(inner, bg=BORDER, height=1)
        # sep_line gepacked zodra er bestanden zijn

        status_row = tk.Frame(inner, bg=SURFACE, padx=10, pady=7)
        status_row.pack(fill="x")

        status_lbl = tk.Label(status_row,
                              text="Sleep bestanden hier of voeg toe…",
                              bg=SURFACE, fg=MUTED,
                              font=("Helvetica Neue", 10), anchor="w")
        status_lbl.pack(side="left", fill="x", expand=True)

        pick_fn = self._pick_ale if file_type == "ALE" else self._pick_pdf
        add_cv  = _rounded_btn(status_row, "Kies…", pick_fn,
                               bg=SURFACE2, hv=BORDER, fg=TEXT,
                               font=("Helvetica Neue", 10), px=10, py=3, r=6,
                               pbg=SURFACE)
        add_cv.pack(side="right")

        def _refresh():
            for w in list_frame.winfo_children():
                w.destroy()

            n = len(paths_list)

            if n == 0:
                status_lbl.config(text="Sleep bestanden hier of voeg toe…")
                list_host.pack_forget()
                sep_line.pack_forget()
            else:
                word = "bestand" if n == 1 else "bestanden"
                status_lbl.config(text=f"{n} {word} geselecteerd")

                for i, p in enumerate(paths_list):
                    row = tk.Frame(list_frame, bg=SURFACE, height=_ROW_H)
                    row.pack(fill="x")
                    row.pack_propagate(False)

                    # Badge
                    bc = tk.Canvas(row, width=32, height=18, bg=SURFACE,
                                   bd=0, highlightthickness=0)
                    bc.pack(side="left", padx=(10, 6), pady=10)
                    bc.create_rectangle(0, 0, 32, 18, fill=badge_color, outline="")
                    bc.create_text(16, 9, text=file_type,
                                   fill="white", font=("Helvetica Neue", 8, "bold"))

                    # Bestandsnaam
                    tk.Label(row, text=Path(p).name, bg=SURFACE, fg=TEXT,
                             font=("Helvetica Neue", 10), anchor="w").pack(
                                 side="left", fill="x", expand=True)

                    # × verwijderknop
                    def _rm(idx=i):
                        paths_list.pop(idx)
                        _refresh()

                    rm = tk.Label(row, text="×", bg=SURFACE, fg=MUTED,
                                  font=("Helvetica Neue", 14), cursor="arrow",
                                  padx=10, pady=0)
                    rm.pack(side="right")
                    rm.bind("<Button-1>", lambda e, fn=_rm: fn())
                    rm.bind("<Enter>",    lambda e, w=rm: w.config(fg=ERROR))
                    rm.bind("<Leave>",    lambda e, w=rm: w.config(fg=MUTED))

                # Canvas hoogte + scrollbar
                vis = min(n, _MAX_V)
                list_cv.configure(height=vis * _ROW_H)

                if n > _MAX_V:
                    if not list_sb.winfo_ismapped():
                        list_sb.pack(side="right", fill="y")
                else:
                    list_sb.pack_forget()

                if not list_cv.winfo_ismapped():
                    list_cv.pack(side="left", fill="both", expand=True)

                # Toon host + separator boven statusbalk
                if not list_host.winfo_ismapped():
                    list_host.pack(fill="x", before=status_row)
                if not sep_line.winfo_ismapped():
                    sep_line.pack(fill="x", before=status_row)

            list_frame.update_idletasks()
            list_cv.configure(scrollregion=list_cv.bbox("all"))

        if file_type == "ALE":
            self._refresh_ale = _refresh
        else:
            self._refresh_pdf = _refresh

        _refresh()
        return outer

    def _file_row(self, parent, var, cmd, lbl_attr, drop_handler=None, file_type=""):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1,
                         bd=0, highlightthickness=0)
        inner = tk.Frame(outer, bg=SURFACE, padx=12, pady=9,
                         bd=0, highlightthickness=0)
        inner.pack(fill="x")

        # Bestandsicoontje
        if file_type == "ALE":
            icon = self._draw_file_icon(inner, "ALE", "#8B30F5", "#5A18C0")
        elif file_type == "PDF":
            icon = self._draw_file_icon(inner, "PDF", "#E8402A", "#AA2010")
        else:
            icon = None
        if icon:
            icon.pack(side="left", padx=(0, 12))

        lbl = tk.Label(inner, text="Sleep bestand hier of kies…", bg=SURFACE, fg=MUTED,
                       font=("Helvetica Neue", 11), anchor="w", cursor="arrow")
        lbl.pack(side="left", fill="x", expand=True)
        setattr(self, lbl_attr, lbl)

        kies_cv = _rounded_btn(inner, "Kies…", cmd,
                               bg=SURFACE2, hv=BORDER, fg=TEXT,
                               font=("Helvetica Neue", 10), px=10, py=4, r=8, pbg=SURFACE)
        kies_cv.pack(side="right")

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
        if p not in self.pdf_paths:
            self.pdf_paths.append(p)
            self._log_direct(f"PDF:  {Path(p).name}", "info")
            self.root.after(0, self._refresh_pdf)

    def _drop_ale(self, event):
        p = self._parse_drop(event.data)
        if p not in self.ale_paths:
            self.ale_paths.append(p)
            self._log_direct(f"ALE:  {Path(p).name}", "info")
            self.root.after(0, self._refresh_ale)

    def _pick_pdf(self):
        paths = filedialog.askopenfilenames(title="Kies PDF bestanden",
                                            filetypes=[("Alle bestanden", "*.*")])
        added = 0
        for p in paths:
            if p not in self.pdf_paths:
                self.pdf_paths.append(p)
                self.log(f"PDF:  {Path(p).name}", "info")
                added += 1
        if added:
            self._refresh_pdf()

    def _pick_ale(self):
        paths = filedialog.askopenfilenames(title="Kies ALE bestanden",
                                            filetypes=[("Alle bestanden", "*.*")])
        added = 0
        for p in paths:
            if p not in self.ale_paths:
                self.ale_paths.append(p)
                self.log(f"ALE:  {Path(p).name}", "info")
                added += 1
        if added:
            self._refresh_ale()

    def _run(self):
        if not self._license_expiry:
            self.log("Geen geldige licentie. Activeer via Continuity Bridge → Licentie…", "err")
            return
        if not self.pdf_paths:
            self.log("Kies eerst een of meer PDF bestanden.", "err"); return
        if not self.ale_paths:
            self.log("Kies eerst een of meer ALE bestanden.", "err"); return
        self._btn_enabled = False
        self._draw_verwerk("Bezig…", disabled=True)
        threading.Thread(target=self._process, daemon=True).start()

    def _process(self):
        try:
            # ── Stap 1: alle PDFs parsen en clips samenvoegen ────────────
            all_clips = {}
            for pdf_p in self.pdf_paths:
                clips = parse_pdf(pdf_p, self.log,
                                  write_pu=self.write_pu_in_notes.get(),
                                  write_afg=self.write_afg_in_notes.get())
                all_clips.update(clips)

            n_pdf = len(self.pdf_paths)
            self.log(f"Totaal: {len(all_clips)} clips uit {n_pdf} PDF('s)", "info")

            # ── Stap 2: elk ALE verwerken en opslaan ─────────────────────
            _out_dir    = self.output_dir.get().strip()
            _out_suffix = self.output_suffix.get().strip() or "_updated_with_notes"
            out_paths = []

            for ale_p in self.ale_paths:
                result = process_ale(ale_p, all_clips, self.log,
                                     write_rating=self.write_rating.get(),
                                     notes_col=(self.notes_col.get()
                                              if self.write_notes.get() else "Uit"),
                                     rating_col=self.rating_col.get(),
                                     sound_notes_col=(self.sound_notes_col.get()
                                                      if self.write_sound_notes.get() else "Uit"),
                                     camera_notes_col=(self.camera_notes_col.get()
                                                       if self.write_camera_notes.get() else "Uit"),
                                     pu_col=(self.pu_col.get()
                                             if self.write_pu_in_notes.get() else "Uit"),
                                     pu_position=self.pu_position.get(),
                                     afg_col=(self.afg_col.get()
                                              if self.write_afg_in_notes.get() else "Uit"),
                                     afg_position=self.afg_position.get(),
                                     general_notes_col=(self.general_notes_col.get()
                                                        if self.write_general_notes.get() else "Uit"))
                stem    = Path(ale_p).stem
                out_dir = Path(_out_dir) if _out_dir else Path(ale_p).parent
                out     = out_dir / f"{stem}{_out_suffix}.ALE"
                result_bytes = result.encode("utf-8")
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(result_bytes)
                except OSError:
                    out = Path.home() / "Desktop" / f"{stem}{_out_suffix}.ALE"
                    out.write_bytes(result_bytes)
                out_paths.append(out)
                self.log(f"Opgeslagen  —  {out.name}", "ok")

            n_ale = len(out_paths)
            self.log(f"✓  Klaar  —  {n_ale} ALE bestand{'en' if n_ale != 1 else ''} opgeslagen", "ok")
            if out_paths:
                import subprocess, sys as _sys
                folder = str(out_paths[0].parent)
                try:
                    if _sys.platform == "darwin":
                        subprocess.Popen(["open", folder])
                    elif _sys.platform.startswith("win"):
                        subprocess.Popen(["explorer", folder])
                    else:
                        subprocess.Popen(["xdg-open", folder])
                except Exception:
                    pass
        except Exception as e:
            self.log(f"Fout: {e}", "err")
        finally:
            def _re_enable():
                self._btn_enabled = True
                self._draw_verwerk("✦  Verwerk")
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
