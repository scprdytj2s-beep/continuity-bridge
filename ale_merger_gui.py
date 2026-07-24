#!/usr/bin/env python3
"""Continuity Bridge GUI - LockitNetwork PDF + ALE combiner"""

import sys, re, os, threading, queue as _queue, unicodedata as _ud
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

# Native macOS drag-and-drop via pure ctypes (geen PyObjC nodig — werkt op Silicon én Intel)
import sys as _sys
HAS_NATIVE_DND = _sys.platform == "darwin"
# NSDragOperationCopy = 1 (AppKit constante, geen import nodig)
_DND_COPY = 1


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
                        if len(row) > 7 and row[7] and re.match(r'^\d{2,4}[A-Za-z]?$', (row[7] or "").strip()):
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
                        take_str = ''.join(c for c in take_str if ord(c) < 128)
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
                    log(f"Fout bij pagina {page.page_number}: {_e}", "warn")
                continue  # LVB pagina verwerkt

            # ── Dag & Nacht / Lemming formaat ─────────────────────────────
            # Eén pagina per slate; KAART = camerarol (bv. "A012"), CLIP = clip-
            # nummer (bv. "C001"); samen → "A012C001" → matcht ALE-prefix.
            if "CONTINUÏTEITSRAPPORT" in text and "KAART" in text and "SLATE" in text:
                try:
                    tbls = page.find_tables()
                    slate = scene = kaart = extra_notes = ""

                    # Tabel met SLATE / SCENE / KAART (rij-georiënteerd)
                    for tbl in tbls:
                        ext = tbl.extract()
                        if not ext: continue
                        for row in ext:
                            if not row or len(row) < 2: continue
                            k = str(row[0] or "").strip()
                            v = str(row[1] or "").strip()
                            if k == "SLATE":  slate = v
                            elif k == "SCENE": scene = v
                            elif k == "KAART": kaart = v
                        if slate and kaart:
                            break

                    if not kaart:
                        continue

                    # EXTRA NOTES tabel
                    for tbl in tbls:
                        ext = tbl.extract()
                        if not ext: continue
                        if str(ext[0][0] or "").strip() == "EXTRA NOTES:":
                            parts = []
                            for row in ext[1:]:
                                if row and row[0]:
                                    v = str(row[0]).strip()
                                    if v and not v.startswith("scriptrapport"):
                                        parts.append(v)
                            extra_notes = " ".join(parts).strip()
                            break

                    # Take-tabel
                    for tbl in tbls:
                        ext = tbl.extract()
                        if not ext: continue
                        headers = [str(c or "").strip() for c in ext[0]]
                        if "TAKE" not in headers or "CLIP" not in headers:
                            continue
                        take_i  = headers.index("TAKE")
                        clip_i  = headers.index("CLIP")
                        pu_i    = headers.index("PU") if "PU" in headers else None
                        notes_i = headers.index("OPMERKINGEN") if "OPMERKINGEN" in headers else None

                        for row in ext[1:]:
                            if not row: continue
                            take_str = str(row[take_i] or "").strip() if take_i < len(row) else ""
                            take_str = ''.join(c for c in take_str if ord(c) < 128)
                            clip_str = str(row[clip_i] or "").strip() if clip_i < len(row) else ""
                            if not take_str or not clip_str: continue
                            if not re.match(r'^\d+$', take_str): continue

                            notes = ""
                            if notes_i is not None and notes_i < len(row):
                                notes = str(row[notes_i] or "").strip().replace("\n", " ")
                                if notes == "-": notes = ""

                            is_pu = (write_pu and pu_i is not None
                                     and pu_i < len(row)
                                     and str(row[pu_i] or "").strip() != "")

                            clip_num = re.sub(r'\s+', '', clip_str)  # "C001"
                            clip_info = {
                                "circle":      "",
                                "scene":       scene,
                                "description": "",
                                "take_notes":  notes or extra_notes,
                                "page_note":   extra_notes,
                                "is_pu":       is_pu,
                            }
                            # Sla op met zowel 3- als 4-cijferige padding zodat
                            # zowel A-cameras (A012C001) als B-cameras (B007C0006)
                            # matchen, ongeacht hoe de camera het bestand noemt.
                            digits_m = re.search(r'\d+', clip_num)
                            if digits_m:
                                n = digits_m.group()
                                for pad in (3, 4):
                                    k = f"{kaart}C{n.zfill(pad)}"
                                    if k not in clips:
                                        clips[k] = dict(clip_info)
                except Exception as _e:
                    log(f"Fout bij pagina {page.page_number}: {_e}", "warn")
                continue  # D&N pagina verwerkt

            # ── TDDOS / CONTINUITY REPORT formaat ─────────────────────────
            # Eén pagina per slate; ROLL NR. geeft clipnaam direct (bv. "A001C002").
            # Meerdere slates kunnen dezelfde ROLL NR. delen → notities aggregeren.
            if "ROLL NR." in text and "CONTINUITY" in text:
                try:
                    tbls = page.find_tables()
                    slate_nr = scene = page_note = ""

                    for tbl in tbls:
                        ext = tbl.extract()
                        if not ext or not ext[0] or len(ext[0]) < 2: continue
                        h0 = str(ext[0][0] or "").strip()
                        h1 = str(ext[0][1] or "").strip()
                        if h0 == "SLATE": slate_nr = h1

                    if not slate_nr:
                        continue

                    sm = re.search(r"SCENE\s+(\S+)", text)
                    if sm: scene = sm.group(1)

                    # Scene-code: "2.30A" → "30A" (deel na de punt)
                    scene_code = scene.split(".")[-1] if "." in scene else scene

                    # Pagina-notities (tabel met header 'Notes' en 1 kolom)
                    for tbl in tbls:
                        ext = tbl.extract()
                        if not ext: continue
                        if str(ext[0][0] or "").strip() == "Notes" and len(ext[0]) == 1:
                            parts = [str(r[0]).replace("\n", " ").strip() for r in ext[1:]
                                     if r and r[0] and str(r[0]).strip()]
                            page_note = " ".join(parts).strip()
                            break

                    # Per-take: notities + sterren → één clip-key per take
                    # Key-formaat: "{scene_code}-{slate:03d}-{take:02d}"
                    # Matcht ALE Name: "02-30A-003-01"
                    for tbl in tbls:
                        ext = tbl.extract()
                        if not ext: continue
                        headers = [str(c or "").strip() for c in ext[0]]
                        if "TAKE" not in headers:
                            continue
                        # "Notes" staat altijd op kolomindex 4 in dit format, maar
                        # pdfplumber laat de headertekst op sommige pagina's leeg
                        # terwijl de data er wél gewoon staat — val dan terug op
                        # de vaste positie i.p.v. de hele pagina over te slaan.
                        if "Notes" in headers:
                            notes_i = headers.index("Notes")
                        elif len(headers) > 4:
                            notes_i = 4
                        else:
                            continue
                        gng_i   = headers.index("G / NG") if "G / NG" in headers else None
                        pu_i    = headers.index("PU") if "PU" in headers else None

                        for ri, row in enumerate(tbl.rows[1:], 1):
                            if ri >= len(ext): break
                            take_str = str(ext[ri][0] or "").strip()
                            take_str = ''.join(c for c in take_str if ord(c) < 128)
                            if not re.match(r'^\d+$', take_str): continue

                            note = str(ext[ri][notes_i] or "").replace("\n", " ").strip() if notes_i < len(ext[ri]) else ""

                            # Sterren tellen via filled curves (≥10 punten)
                            stars = 0
                            if gng_i is not None:
                                try:
                                    cell = row.cells[gng_i]
                                    x0, top, x1, bottom = cell
                                    crop = page.crop((x0, top, x1, bottom))
                                    stars = sum(1 for c in crop.curves
                                                if c.get('fill') and len(c.get('pts', [])) >= 10)
                                except Exception:
                                    pass

                            # PU detecteren via pixel-analyse (checkmark = donkere pixels)
                            is_pu = False
                            if write_pu and pu_i is not None:
                                try:
                                    pu_cell = row.cells[pu_i]
                                    px0, ptop, px1, pbottom = pu_cell
                                    pu_crop = page.crop((px0, ptop, px1, pbottom))
                                    pu_img  = pu_crop.to_image(resolution=150).original.convert('L')
                                    pw, ph  = pu_img.size
                                    dark    = sum(1 for py in range(ph) for px in range(pw)
                                                  if pu_img.getpixel((px, py)) < 80)
                                    is_pu   = dark >= 30
                                except Exception:
                                    pass

                            if not note and not stars and not is_pu:
                                continue

                            try:
                                # Key: alleen slate+take (geen scene-code — die verschilt
                                # tussen PDF-notatie en ALE-naamgeving)
                                key = f"{int(slate_nr):03d}-{int(take_str):02d}"
                            except ValueError:
                                continue

                            if key not in clips:
                                clips[key] = {
                                    "circle":      "",
                                    "scene":       scene,
                                    "description": "",
                                    "take_notes":  note or page_note,
                                    "page_note":   page_note,
                                    "is_pu":       is_pu,
                                    "stars":       str(stars) if stars else "",
                                }

                except Exception as _e:
                    log(f"Fout bij pagina {page.page_number}: {_e}", "warn")
                continue  # TDDOS pagina verwerkt

            # ── LockitNetwork Editors Log (DE) ────────────────────────────
            # Duits formaat: per pagina meerdere camera-secties (Cam A, Cam BCP).
            # Kolommen: Take | Clip | K/NK | Länge | Take Kommentar
            # K = Gut (goed), NK = Nicht Gut (afgekeurd)
            if "K/NK" in text and "Cam " in text and "Länge" in text:
                try:
                    m_set   = re.search(r'Set:\s*(.+?)\s+Einst\.\s*:\s*(\d+)', text)
                    set_name = m_set.group(1).strip() if m_set else ""
                    einst    = m_set.group(2) if m_set else ""
                    scene_label = f"{set_name} E{einst}" if set_name else ""

                    # Beschrijving per camera: "Einstellungsbeschreibung: A: ... BCP: ..."
                    cam_desc: dict[str, str] = {}
                    einst_m = re.search(r'Einstellungs-\s*beschreibung:\s*(.*?)(?=Synopsis:|Szenenkommentar:|$)',
                                        text, re.DOTALL)
                    if einst_m:
                        einst_text = einst_m.group(1).replace('\n', ' ')
                        for dm in re.finditer(r'(\w+):\s*(.+?)(?=\s+\w+:|$)', einst_text):
                            cam_desc[dm.group(1)] = dm.group(2).strip()

                    cur_cam = ""
                    for t in page.extract_tables():
                        for row in t:
                            if not row: continue
                            cell0 = str(row[0] or "").strip()

                            # Camera-kop: "Cam A Rolle(n): A001 Ton: 1"
                            m_cam = re.match(r'Cam\s+(\w+)\s+Rolle', cell0)
                            if m_cam:
                                cur_cam = m_cam.group(1)  # "A", "BCP", "B", …
                                continue

                            # Header-rij overslaan
                            if cell0 == "Take":
                                continue

                            # Take-rij
                            if not re.match(r'^\d+$', cell0):
                                continue
                            if len(row) < 3:
                                continue

                            clip_name = str(row[1] or "").strip()
                            knk       = str(row[2] or "").strip()  # "K" of "NK"
                            notes     = (str(row[4] or "").strip().replace("\n", " ")
                                         if len(row) > 4 else "")

                            circle = "K" if knk == "K" else ("NK" if knk == "NK" else knk)
                            desc   = cam_desc.get(cur_cam, "")

                            clip_info = {
                                "circle":      circle,
                                "scene":       scene_label,
                                "description": desc,
                                "take_notes":  notes,
                                "page_note":   "",
                                "is_pu":       False,
                                "stars":       "",
                            }

                            # Sla op met clip_name als primaire sleutel
                            # (A-camera: "A001C002" → prefix-match op ALE-naam)
                            if clip_name and clip_name not in clips:
                                clips[clip_name] = clip_info

                            # BCP-camera: ook opslaan als "LNDE_B:{rol:03d}:{clip:03d}"
                            # voor matching op ALE-namen als "B001_05301052_C002"
                            m_bcp = re.match(r'BCP_(\d+)_C(\d+)', clip_name)
                            if m_bcp:
                                lnde_key = f"LNDE_B:{int(m_bcp.group(1)):03d}:{int(m_bcp.group(2)):03d}"
                                if lnde_key not in clips:
                                    clips[lnde_key] = clip_info

                except Exception as _e:
                    log(f"Fout bij pagina {page.page_number}: {_e}", "warn")
                continue  # LockitNetwork DE pagina verwerkt

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
                # Horizontale witruimte ([ \t]) i.p.v. \s: anders eet een cirkel die
                # als laatste op de regel staat de newline op en slokt de vólgende
                # take-regel (incl. diens rating) op.
                for m in re.finditer(r"^(\d+[A-Z]*|[A-Z]+)[ \t]+(A\d{3}C\d{3})[ \t]+(?:\d{1,2}(?::\d{2})+[ \t]+)?([✓\-X])[ \t]*(.*)", tm.group(1), re.MULTILINE):
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

    # ── Aangepaste layouts als fallback ──────────────────────────────────────
    if not clips:
        with pdfplumber.open(pdf_path) as pdf2:
            for page2 in pdf2.pages:
                for tbl in page2.extract_tables():
                    if not tbl or len(tbl) < 2:
                        continue
                    headers = [str(c or "").strip() for c in tbl[0]]
                    layout  = _find_layout(headers)
                    if layout:
                        clips.update(_parse_pdf_custom(pdf_path, layout, log))
                        break
                if clips:
                    break

    # Onbekend formaat — signaal voor de mapper UI
    if not clips:
        return None

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
                pu_eigen_kolom=False, pu_eigen_kolom_naam="PU",
                afg_col="Auto", afg_position="voor",
                general_notes_col="Auto", star_format="sterren",
                scene_col="Auto"):
    with open(ale_path, "rb") as f:
        raw = f.read()

    # Bewaar originele line endings
    if b"\r\n" in raw:
        le = "\r\n"
    elif b"\r" in raw:
        le = "\r"
    else:
        le = "\n"

    # Encoding detecteren en onthouden voor de output (round-trip). Moderne Avid
    # exporteert UTF-8; oudere Avid (zonder UTF-8-optie) exporteert Mac Roman.
    try:
        text = raw.decode("utf-8")
        src_encoding = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("mac_roman", errors="replace")
        src_encoding = "mac_roman"
    lines = text.splitlines()

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
        name_l = name.lower()
        for i, h in enumerate(col_headers):
            if h.lower() == name_l:
                return i
        return None

    name_idx  = idx("Name")
    tape_idx  = idx("Tape")
    # Scene-doelkolom: "Uit" = niet schrijven (bewaar originele bin-scene),
    # "Auto" = bestaande Scene-kolom bijwerken, anders gekozen/nieuwe kolom.
    if scene_col in ("Uit", "Off", "Aus", ""):
        scene_idx = None
    elif scene_col and scene_col != "Auto":
        scene_idx = idx(scene_col)
        if scene_idx is None:
            col_headers.append(scene_col)
            scene_idx = len(col_headers) - 1
            log(f"Kolom '{scene_col}' niet gevonden — toegevoegd aan ALE.", "info")
    else:
        scene_idx = idx("Scene")   # alleen bijwerken als al aanwezig
    desc_idx  = idx("Description") # alleen bijwerken als al aanwezig

    # Tracks-kolom is verplicht voor Avid ALE-import — voeg toe als afwezig
    tracks_idx = idx("Tracks")
    if tracks_idx is None:
        col_headers.append("Tracks")
        tracks_idx = len(col_headers) - 1
        log("Geen Tracks-kolom gevonden — 'Tracks' met waarde 'V' toegevoegd.", "info")

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
                (idx(c) for c in ("Take_notes", "Comment", "Note", "Notes", "Comments")
                 if idx(c) is not None),
                None
            )
            if take_notes_idx is None:
                col_headers.append("Take_notes")
                take_notes_idx = len(col_headers) - 1
                log("Geen notes-kolom gevonden — 'Take_notes' toegevoegd aan ALE.", "info")

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

    # PU eigen kolom (aparte kolom met alleen "PU" als waarde)
    pu_eigen_idx = None
    if pu_eigen_kolom and pu_eigen_kolom_naam:
        _pu_ek = pu_eigen_kolom_naam.strip() or "PU"
        if _pu_ek not in col_headers:
            col_headers.append(_pu_ek)
            log(f"Kolom '{_pu_ek}' toegevoegd aan ALE (PU markering).", "info")
        pu_eigen_idx = col_headers.index(_pu_ek)

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

    # Bepaal of originele datarijen een trailing tab hebben (bewaar dit gedrag)
    _orig_has_trailing_tab = any(
        l.endswith("\t") for l in lines[data_idx + 1:] if l.strip()
    )

    matched = 0
    new_data_lines = []
    for line in lines[data_idx + 1:]:
        if not line.strip():
            new_data_lines.append(line); continue
        parts = line.split("\t")[:n_orig]
        while len(parts) < n_orig: parts.append("")
        for _ in new_cols:
            parts.append("")
        # Tracks standaard 'V' als kolom nieuw is (was afwezig in origineel)
        if tracks_idx is not None and tracks_idx >= n_orig and not parts[tracks_idx]:
            parts[tracks_idx] = "V"
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

        # TDDOS: ALE Name "DD-SCENE-SLATE-TAKE" → key "SLATE-TAKE"
        # bv. "02-30B-009-01" → zoek "009-01" in clip_data
        if info is None:
            m_tddos = re.match(r'\d+-\S+?-(\d{3})-(\d+)', parts[name_idx])
            if m_tddos:
                tddos_key = f"{m_tddos.group(1)}-{m_tddos.group(2).zfill(2)}"
                info = clip_data.get(tddos_key)

        # LockitNetwork DE: BCP-camera ALE-naam "B001_05301052_C002" → "LNDE_B:001:002"
        if info is None:
            m_lnde = re.match(r'^B(\d{3})_\d+_C(\d+)', parts[name_idx])
            if m_lnde:
                lnde_key = f"LNDE_B:{m_lnde.group(1)}:{int(m_lnde.group(2)):03d}"
                info = clip_data.get(lnde_key)

        # Wis altijd bestaande camera-rating (bv. "0" of "5") zodat alleen CB-waarden overblijven
        if write_rating and rating_idx is not None and rating_idx < len(parts):
            parts[rating_idx] = ""

        if info:
            matched += 1
            if write_rating and rating_idx is not None:
                if info.get("stars"):
                    try:
                        n = int(info["stars"])
                        if star_format == "sterren":
                            parts[rating_idx] = "*" * n
                        elif star_format == "letters":
                            parts[rating_idx] = ("A","B","C","D","E","")[max(0, min(5-n, 5))]
                        else:
                            parts[rating_idx] = str(n)
                    except (ValueError, TypeError):
                        parts[rating_idx] = info["stars"]
                elif info.get("circle"):
                    parts[rating_idx] = info["circle"]  # V/X pass-through
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
            # Stars (apart, nooit samenvoegen) — zelfde format als rating
            if stars_idx is not None and info.get("stars"):
                try:
                    n = int(info["stars"])
                    if star_format == "sterren":
                        parts[stars_idx] = "*" * n
                    elif star_format == "letters":
                        parts[stars_idx] = ("A","B","C","D","E","")[max(0, min(5-n, 5))]
                    else:
                        parts[stars_idx] = str(n)
                except (ValueError, TypeError):
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
            # PU eigen kolom — schrijf gewoon "PU" (geen tekst, geen positie)
            if info.get("is_pu") and pu_eigen_idx is not None:
                parts[pu_eigen_idx] = "PU"
        parts = [p.replace("\t", " ").replace("\r", " ").replace("\n", " ") for p in parts]
        new_data_lines.append(parts)  # bewaar als list; joinen gebeurt hieronder

    log(t("log_ale_matched", n=matched), "info")

    # Volledig lege kolommen wegstrippen. Sommige ALE-exports (bv. Sony Venice
    # via een Avid-bin) bevatten tientallen lege metadata-kolommen, soms met
    # afgekapte dubbele namen — Avid kan zijn eigen export dan niet terug
    # importeren ("syntax error in timecode field"). Lege kolommen dragen geen
    # data, dus verwijderen is verliesvrij.
    n_cols = len(col_headers)
    col_has_data = [False] * n_cols
    for row in new_data_lines:
        if isinstance(row, list):
            for i, v in enumerate(row[:n_cols]):
                if v.strip():
                    col_has_data[i] = True
    # Essentiële kolommen altijd behouden, ook als (toevallig) leeg
    _protect = {name_idx, rating_idx, take_notes_idx, tracks_idx, tape_idx}
    for _c in ("Name", "Start", "End", "Duration", "Source File"):
        _protect.add(idx(_c))
    _protect.discard(None)
    keep = [i for i in range(n_cols) if col_has_data[i] or i in _protect]
    dropped = n_cols - len(keep)

    if dropped:
        col_headers = [col_headers[i] for i in keep]
        for j, row in enumerate(new_data_lines):
            if isinstance(row, list):
                new_data_lines[j] = "\t".join(
                    row[i] if i < len(row) else "" for i in keep)
        log(f"{dropped} lege kolommen verwijderd voor Avid-compatibiliteit.", "info")
        _hdr_sep = ""
    else:
        for j, row in enumerate(new_data_lines):
            if isinstance(row, list):
                s = "\t".join(row)
                if new_cols or _orig_has_trailing_tab:
                    s += "\t"
                new_data_lines[j] = s
        _hdr_sep = "\t" if (new_cols or lines[col_idx + 1].endswith("\t")) else ""

    out_lines = lines[:col_idx] + ["Column", "\t".join(col_headers) + _hdr_sep, "", "Data"] + new_data_lines
    result = le.join(out_lines)
    if raw.endswith(le.encode()):
        result += le
    return result, src_encoding


# ---------------------------------------------------------------------------
# AVB BIN WRITER (alternatief voor ALE-export/re-import)
# ---------------------------------------------------------------------------

def process_avb(avb_path, out_path, clip_data, log, write_rating=True, write_notes=True,
                 star_format="sterren"):
    """Schrijft PDF-continuity-data direct in een Avid .avb-bin i.p.v. een ALE
    te exporteren die je zelf terug moet importeren. Matcht elke Composition-mob
    op zijn eigen 'Slate'/'Take' user-attributen (sleutel "SLATE-TAKE", dezelfde
    vorm als parse_pdf() produceert) — geen naam-regex nodig zoals bij ALE.
    Schrijft altijd naar out_path (nieuw bestand); het origineel wordt nooit
    geopend voor schrijven, dus de bin in gebruik blijft veilig ongewijzigd."""
    import avb
    matched = 0
    missing_cols = set()
    with avb.open(str(avb_path)) as f:
        for mob in f.content.mobs:
            u = mob.attributes.get('_USER')
            if u is None:
                continue
            slate = str(u.get('Slate') or '').strip()
            take  = str(u.get('Take')  or '').strip()
            if not slate or not take:
                continue
            try:
                key = f"{int(slate):03d}-{int(take):02d}"
            except ValueError:
                continue
            info = clip_data.get(key)
            if not info:
                continue
            matched += 1

            if write_notes and info.get("take_notes"):
                if "Comment" in u:
                    u["Comment"] = info["take_notes"]
                else:
                    missing_cols.add("Comment")

            if write_rating and info.get("stars"):
                try:
                    n = int(info["stars"])
                    if star_format == "sterren":
                        val = "*" * n
                    elif star_format == "letters":
                        val = ("A", "B", "C", "D", "E", "")[max(0, min(5 - n, 5))]
                    else:
                        val = str(n)
                except (ValueError, TypeError):
                    val = info["stars"]
                for col in ("Rating", "Stars"):
                    if col in u:
                        u[col] = val
                    else:
                        missing_cols.add(col)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        f.write(str(out_path))

    log(f"AVB verwerkt: {matched} clip(s) gematcht op Scene/Slate/Take", "info")
    for col in sorted(missing_cols):
        log(f"Let op: kolom '{col}' bestaat niet in deze bin — genegeerd.", "warn")
    return matched


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# macOS 26+ COMPATIBILITY PATCH
# NSMenuItem initWithTitle:action:keyEquivalent: rejects empty string titles.
# Tk creates menu items with empty titles during init → crash.
# Two-layer fix: NSAssertionHandler suppresses the assertion, AND we swizzle
# the method to replace empty titles with a retained NSString.
# ---------------------------------------------------------------------------
def _patch_nsmenuitem_for_macos15plus():
    import sys, platform as _plat
    if sys.platform != 'darwin':
        return
    try:
        int(_plat.mac_ver()[0].split('.')[0])  # controleert dat het macOS is met een versienummer
    except Exception:
        return

    # ── Layer 1: NSAssertionHandler — suppress the assertion before it raises ──
    try:
        import objc as _objc
        from Foundation import NSAssertionHandler as _NSAHandler, NSThread as _NSThread

        class _SilentHandler(_NSAHandler):
            def handleFailureInMethod_object_file_lineNumber_description_(
                    self, sel, obj, fn, ln, desc):
                pass  # swallow — we handle it in the swizzle below
            def handleFailureInFunction_file_lineNumber_description_(
                    self, fn_name, fn, ln, desc):
                pass

        _h = _SilentHandler.alloc().init()
        _NSThread.mainThread().threadDictionary()['NSAssertionHandler'] = _h
        _patch_nsmenuitem_for_macos15plus._handler = _h
    except Exception:
        pass

    # ── Layer 2: method swizzle — replace empty title with retained NSString ──
    try:
        import ctypes
        libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        libobjc.objc_getClass.restype             = ctypes.c_void_p
        libobjc.objc_getClass.argtypes            = [ctypes.c_char_p]
        libobjc.sel_registerName.restype          = ctypes.c_void_p
        libobjc.sel_registerName.argtypes         = [ctypes.c_char_p]
        libobjc.class_getInstanceMethod.restype   = ctypes.c_void_p
        libobjc.class_getInstanceMethod.argtypes  = [ctypes.c_void_p, ctypes.c_void_p]
        libobjc.method_getImplementation.restype  = ctypes.c_void_p
        libobjc.method_getImplementation.argtypes = [ctypes.c_void_p]
        libobjc.method_setImplementation.restype  = ctypes.c_void_p
        libobjc.method_setImplementation.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        cls      = libobjc.objc_getClass(b'NSMenuItem')
        sel_init = libobjc.sel_registerName(b'initWithTitle:action:keyEquivalent:')
        method   = libobjc.class_getInstanceMethod(cls, sel_init)
        orig_imp = libobjc.method_getImplementation(method)

        IMP_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        )
        _orig_fn = IMP_TYPE(orig_imp)

        # Build a RETAINED NSString @" " via [[NSString alloc] initWithUTF8String:]
        _sa_ptr = ctypes.cast(libobjc.objc_msgSend, ctypes.c_void_p).value

        _nsstr_cls  = libobjc.objc_getClass(b'NSString')
        _sel_alloc   = libobjc.sel_registerName(b'alloc')
        _sel_initUTF = libobjc.sel_registerName(b'initWithUTF8String:')
        _sel_len     = libobjc.sel_registerName(b'length')

        # [NSString alloc] — 2-arg msgSend
        _fn_alloc = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(_sa_ptr)
        _alloc_obj = _fn_alloc(_nsstr_cls, _sel_alloc)

        # [alloc_obj initWithUTF8String:" "] — 3-arg msgSend, retain count = 1
        _fn_init = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
        )(_sa_ptr)
        _space = _fn_init(_alloc_obj, _sel_initUTF, b' ')

        def _get_len(obj):
            _fn_len = ctypes.CFUNCTYPE(
                ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p
            )(_sa_ptr)
            return _fn_len(obj, _sel_len)

        def _patched(self_, cmd, title, action, key):
            try:
                # NSString nil pointer check via objc_msgSend
                if not title or _get_len(title) == 0:
                    title = _space
            except Exception:
                title = _space
            return _orig_fn(self_, cmd, title, action, key)

        _new_imp = IMP_TYPE(_patched)
        _patch_nsmenuitem_for_macos15plus._orig  = _orig_fn
        _patch_nsmenuitem_for_macos15plus._new   = _new_imp
        _patch_nsmenuitem_for_macos15plus._space = _space
        libobjc.method_setImplementation(method, ctypes.cast(_new_imp, ctypes.c_void_p))
    except Exception:
        pass

_patch_nsmenuitem_for_macos15plus()

# ---------------------------------------------------------------------------
# GUI  —  Avid-stijl kleurenpalet
# ---------------------------------------------------------------------------

VERSION       = "1.3.9.2 (Beta)"

# ── Vertalingen ────────────────────────────────────────────────────────────────
STRINGS: dict[str, dict[str, str]] = {
    "nl": {
        # Vensterttitels
        "wintitle_main":           "Continuity Bridge",
        "wintitle_prefs":          "Voorkeuren",
        "wintitle_faq":            "FAQ — Continuity Bridge",
        "wintitle_about":          "Over Continuity Bridge",
        "wintitle_license":        "Licentie activeren",
        "wintitle_license_info":   "Licentie",
        "wintitle_update":         "Update beschikbaar",
        "wintitle_no_update":      "Geen updates",
        "wintitle_update_check":   "Update-check",
        "wintitle_layout":         "Rapport herkennen",
        "wintitle_sold":           "Verkochte licenties",
        "wintitle_col_pick":       "Kies kolom",
        "wintitle_revoke":         "Licentie intrekken",
        "wintitle_remove_lic":     "Licentie verwijderen",
        "wintitle_lic_question":   "Licentie",
        # Menubar
        "menu_about":              "Over Continuity Bridge",
        "menu_prefs":              "Voorkeuren…",
        "menu_quit":               "Beëindig Continuity Bridge",
        "menu_license":            "Licentie…",
        "menu_remove_license":     "Verwijder licentie…",
        "menu_faq":                "FAQ…",
        "menu_check_updates":      "Check voor updates…",
        # Sectielabels hoofdscherm
        "section_ale":             "Avid Log Exchange file (ALE)",
        "section_pdf":             "Continuïteitsrapport (PDF)",
        "section_notes_col":       "Notes → kolom",
        # Bestandswidget
        "file_drop_hint":          "Sleep bestanden hier of voeg toe…",
        "file_n_selected":         "{n} {word} geselecteerd",
        "file_word_single":        "bestand",
        "file_word_plural":        "bestanden",
        "btn_choose":              "Kies…",
        # Hints
        "hint_more_settings":      "⚙  Meer instellingen in Voorkeuren  (⌘,)",
        "btn_clear_all":           "↺  Wis alles",
        "btn_process":             "✦  Verwerk",
        "btn_busy":                "Bezig…",
        # Voorkeuren-venster
        "prefs_title":             "Voorkeuren",
        "prefs_section_per_take":  "PER TAKE",
        "prefs_section_general":   "ALGEMENE OPMERKINGEN PER SLATE",
        "prefs_notes":             "Notes",
        "prefs_scene":             "Scene",
        "prefs_rating":            "Rating",
        "prefs_stars_as":          "sterren als:",
        "prefs_stars_stars":       "sterren (***)",
        "prefs_stars_number":      "cijfer (1-5)",
        "prefs_stars_letter":      "letters (X/V)",
        "prefs_write_pu":          "Schrijf (PU)",
        "prefs_pu_own_col":        "PU in eigen kolom",
        "prefs_pu_col_name":       "Kolomnaam",
        "prefs_write_afg":         "Schrijf (AFG)",
        "prefs_position":          "positie:",
        "prefs_pos_before":        "voor",
        "prefs_pos_after":         "achter",
        "prefs_sound_notes":       "Sound Notes",
        "prefs_camera_notes":      "Camera Notes",
        "prefs_opmerkingen":       "Opmerkingen",
        "prefs_output_dir":        "Uitvoermap",
        "prefs_output_dir_hint":   "(leeg = zelfde map als ALE)",
        "prefs_filename":          "Bestandsnaam",
        "prefs_filename_orig":     "{originele naam}",
        "btn_close":               "Sluit",
        "btn_choose_dir":          "Kies…",
        "prefs_lang_label":        "Taal / Language / Sprache",
        "prefs_lang_restart_hint": "Herstart de app om de taal toe te passen",
        # Log-berichten
        "log_ale_matched":         "ALE verwerkt: {n} clips bijgewerkt",
        "log_saved":               "Opgeslagen  —  {name}",
        "log_done_one":            "✓  Klaar  —  1 ALE bestand opgeslagen",
        "log_done_many":           "✓  Klaar  —  {n} ALE bestanden opgeslagen",
        "ask_clear_title":         "Volgende draaidag?",
        "ask_clear_msg":           "Velden wissen voor de volgende draaidag?",
        "btn_clear_yes":           "Wis",
        "btn_clear_no":            "Laat staan",
        "prefs_open_folder":       "Map openen na verwerken",
        "prefs_translit":          "Umlauten omzetten (ü→ue, ö→oe, ä→ae, ß→ss)",
        "prefs_ale_encoding":      "ALE-codering",
        "enc_auto":                "Auto (zoals invoer)",
        "enc_utf8":                "UTF-8 (nieuwere Avid)",
        "enc_macroman":            "Mac Roman (oudere Avid)",
        "prefs_ui_scale":          "Interfacegrootte",
        "prefs_ui_font":           "Lettertype",
        "prefs_accent":            "Accentkleur",
        "font_helvetica":          "Standaard",
        "font_systeem":            "Systeem",
        "font_leesbaar":           "Leesbaar",
        "prefs_section_appearance": "UITERLIJK",
        "prefs_section_output":    "UITVOER",
        "prefs_section_language":  "TAAL",
        "prefs_reset_scale":       "Standaard (100%)",
        "prefs_clear_label":       "Wissen na verwerken",
        "prefs_clear_delay":       "Vertraging",
        "clear_mode_uit":          "Uit",
        "clear_mode_vragen":       "Vragen",
        "clear_mode_auto":         "Automatisch",
        "clear_delay_unit":        "sec",
        # Kolom-picker
        "col_pick_search":         "Zoek:",
        "col_pick_own_label":      "Of typ eigen naam:",
        "btn_cancel":              "Annuleer",
        "btn_pick":                "Kies",
        "col_pick_placeholder":    "Kies kolom…",
        # Update-dialoog
        "update_available":        "Versie {ver} beschikbaar",
        "update_you_have":         "Jij hebt {ver}",
        "update_btn_install":      "Update & Herstart",
        "update_btn_later":        "Later",
        "update_status_download":  "Downloaden… {kb} KB",
        "update_status_install":   "Installeren…",
        "update_status_done":      "Update klaar!",
        "update_win_status_done":  "Installer gestart — volg de instructies.",
        "update_btn_restart":      "\U0001f504  Herstart app",
        "update_error_prefix":     "Fout: ",
        "update_no_update_msg":    "Je hebt de nieuwste versie ({ver}).",
        "update_fetch_error":      "Kon de versie-info niet ophalen.\nControleer je internetverbinding of kijk op:\ngithub.com/{repo}/releases",
        # Over-venster
        "about_version":           "Versie {ver}",
        "about_author":            "by Michiel Boesveldt  © 2026",
        "btn_ok":                  "OK",
        # Licentie-dialoog
        "lic_name_label":          "Naam",
        "lic_serial_label":        "Serienummer",
        "lic_btn_activate":        "Activeer",
        "lic_btn_buy":             "\U0001f6d2  Koop licentie",
        "lic_buy_after":           "Na betaling ontvang je serial per mail.",
        "lic_verify_msg":          "Activatie verifiëren…",
        "lic_name_mismatch":       "✗ Naam komt niet overeen met licentie.",
        "lic_already_bound":       "✗ Serial al geactiveerd op een andere machine.\nNeem contact op met support@studiomichielboesveldt.nl",
        "lic_removed_msg":         "Licentie verwijderd. Voer een nieuw serienummer in.",
        "lic_remove_confirm":      "Licentie verwijderen van deze Mac?\n\nJe moet daarna een nieuw serienummer invoeren.",
        "lic_ask_new_serial":      "Nieuw serienummer invoeren?",
        "lic_active_label":        "✓  Actief",
        # Licentiebeheer
        "mgr_token_label":         "GitHub manager token:",
        "mgr_btn_save_load":       "Opslaan & laden",
        "mgr_enter_token":         "Voer je GitHub manager token in.",
        "mgr_loading":             "Laden…",
        "mgr_status_valid":        "Geldig",
        "mgr_status_expired":      "Verlopen",
        "mgr_status_revoked":      "Ingetrokken",
        "mgr_revoke_btn":          "⊘  Intrek geselecteerde licentie",
        "mgr_revoke_confirm":      "Licentie van {naam} intrekken?\n\n{serial}\n\nDit kan niet ongedaan worden gemaakt.",
        "mgr_revoking":            "Licentie intrekken…",
        "mgr_revoked_ok":          "Ingetrokken: {serial}…",
        "mgr_revoke_err":          "Fout bij intrekken: {err}",
        "mgr_fetch_err":           "Fout: {err}",
        # Layout mapper
        "layout_unknown_format":   "Onbekend rapport-formaat",
        "layout_hint":             "{fname}  —  wijs aan welke kolom wat betekent.",
        "layout_name_label":       "Naam voor dit formaat:",
        "layout_no_take_col":      "Wijs minimaal de kolom 'Take' aan.",
        "btn_detect_process":      "Herken & verwerk",
        "btn_skip":                "Overslaan",
        "field_ignore":            "— negeer —",
        "field_slate_scene":       "Slate / Scene",
        "field_take":              "Take",
        "field_note":              "Opmerking / Note",
        "field_rating":            "Rating (V/X)",
        "field_camera_roll":       "Camerarol",
        # Bestandsdialogen
        "dlg_pick_pdf":            "Kies PDF bestanden",
        "dlg_pick_ale":            "Kies ALE bestanden",
        "dlg_pick_dir":            "Kies uitvoermap",
        # Run-fouten
        "err_no_license":          "Geen geldige licentie. Activeer via Continuity Bridge → Licentie…",
        "err_no_pdf":              "Kies eerst een of meer PDF bestanden.",
        "err_no_ale":              "Kies eerst een of meer ALE bestanden.",
        # FAQ
        "faq_title":               "FAQ",
        "faq_subtitle":            "Veelgestelde vragen over Continuity Bridge",
        "faq_q1":  "Hoe importeer ik het verwerkte ALE terug in Avid?",
        "faq_a1":  "Ga in Avid naar Preferences → User → Import → Shot Log. "
                   "Kies onder Events de optie 'Merge events with known master clips'. "
                   "Zo voegt Avid de comments en ratings toe aan je bestaande clips "
                   "in plaats van nieuwe clips aan te maken.",
        "faq_q2":  "Welke PDF-formaten worden ondersteund?",
        "faq_a2":  "Continuity Bridge ondersteunt de meeste gangbare continuïteitsrapporten. "
                   "Werkt jouw rapport niet goed? Meld het via het bugrapport op "
                   "https://studiomichielboesveldt.nl/cbapp/feedback of mail "
                   "support@studiomichielboesveldt.nl. We kijken ernaar.",
        "faq_q3":  "Verdwijnt mijn info na het maken van een multiclip?",
        "faq_a3":  "Dat kan. Importeer de ALE altijd vóórdat je multiclips aanmaakt. "
                   "Avid draagt metadata niet automatisch over aan bestaande multiclips.",
        "faq_q4":  "Ik krijg een waarschuwing dat de app van een onbekende ontwikkelaar is.",
        "faq_a4":  "Dit is standaard macOS-beveiliging voor apps buiten de App Store. "
                   "Klik NIET op 'Verplaats naar prullenmand'!\n\n"
                   "Zo open je de app:\n"
                   "1. Klik in de melding op 'Gereed' (Done)\n"
                   "2. Open Systeeminstellingen → Privacy en beveiliging, scroll omlaag\n"
                   "3. Daar staat nu '\"Continuity Bridge\" is geblokkeerd…' → klik 'Toch openen'\n"
                   "4. Bevestig eenmalig met Touch ID of je wachtwoord\n\n"
                   "Dit hoeft maar één keer, daarna onthoudt macOS het. Updates via de "
                   "in-app updater hebben hier geen last van. We werken aan een Apple "
                   "Developer-registratie zodat deze melding helemaal verdwijnt.",
        "faq_q5":  "Werkt Continuity Bridge offline?",
        "faq_a5":  "Ja, volledig. Na activatie heeft de app geen internetverbinding nodig. "
                   "Verwerking gebeurt lokaal op je Mac of pc.",
        "faq_q6":  "Kan ik de licentie op meerdere Macs gebruiken?",
        "faq_a6":  "Een licentie is gekoppeld aan één machine. Ga je over naar een nieuwe Mac? "
                   "Verwijder de licentie eerst via Help → Verwijder licentie, en activeer "
                   "daarna op je nieuwe Mac. Ben je dat vergeten? "
                   "Mail naar support@studiomichielboesveldt.nl.",
        "faq_q7":  "Wat gebeurt er als mijn licentie verloopt?",
        "faq_a7":  "Na een jaar stopt de app met verwerken totdat je verlengt. "
                   "Je bestanden blijven gewoon intact — er verdwijnt niets.",
        "faq_q8":  "Mijn clips worden niet herkend. Wat nu?",
        "faq_a8":  "Controleer of de clipnamen in je ALE overeenkomen met de namen in het "
                   "continuïteitsrapport. Kleine afwijkingen kunnen een mismatch geven. "
                   "Lukt het niet? Meld het via het bugrapport op "
                   "https://studiomichielboesveldt.nl/cbapp/feedback of mail "
                   "support@studiomichielboesveldt.nl.",
        "faq_q9":  "Avid vraagt bij import 'Tape name matches up to maximum length / Merge?'",
        "faq_a9":  "Dit is normaal Avid-gedrag, geen fout. Je klikt gewoon op 'Yes To All'.\n\n"
                   "Waarom het gebeurt: Avid bewaart clip-namen met maximaal 32 tekens. "
                   "Drone-clips hebben langere namen (vaak 45+ tekens). De clip staat dus in je "
                   "bin onder de ingekorte naam, terwijl de ALE de volledige naam bevat. Avid "
                   "ziet dat de eerste 32 tekens gelijk zijn en vraagt voor de zekerheid: is dit "
                   "dezelfde clip, samenvoegen?\n\n"
                   "Klik 'Yes To All' = ja, het is dezelfde clip. Je continuiteitsdata wordt dan "
                   "netjes aan de bestaande clips gekoppeld. Er gaat niets verloren.\n\n"
                   "Continuity Bridge kan deze vraag niet wegnemen: als het de namen zou inkorten "
                   "tot 32 tekens, zou Avid de clips juist helemaal niet meer terugvinden.",
        "faq_q10": "Hoe exporteer ik een ALE vanuit Avid, en moet 'UTF-8' aan?",
        "faq_a10": "Exporteer bij voorkeur vanuit een ruwe beeld-bin met de originele "
                   "cameraclip-namen. Dat geeft de betrouwbaarste match. Selecteer de clips (of "
                   "de bin) en kies File > Output > Export, met als formaat 'Avid Log Exchange "
                   "(ALE)'.\n\n"
                   "De optie 'UTF-8 Encoding' mag gerust aan blijven. Continuity Bridge leest "
                   "zowel UTF-8 als de oudere codering, dus het maakt niet uit.\n\n"
                   "Importeer het verwerkte ALE weer in diezelfde beeld-bin (aangeraden). "
                   "Gekoppelde sync-clips, subclips en scenes nemen de toegevoegde data (rating, "
                   "notities) automatisch over van de masterclips.\n\n"
                   "Tip: zet of maak in je Avid-bin alvast de kolommen aan die je wilt gebruiken "
                   "(bv. Rating, Take_notes, Comment) voordat je exporteert. Dan bestaan ze al in "
                   "de ALE en komt de data na het importeren meteen in de juiste kolommen terecht.",
    },
    "en": {
        # Window titles
        "wintitle_main":           "Continuity Bridge",
        "wintitle_prefs":          "Preferences",
        "wintitle_faq":            "FAQ — Continuity Bridge",
        "wintitle_about":          "About Continuity Bridge",
        "wintitle_license":        "Activate License",
        "wintitle_license_info":   "License",
        "wintitle_update":         "Update Available",
        "wintitle_no_update":      "No Updates",
        "wintitle_update_check":   "Update Check",
        "wintitle_layout":         "Recognize Report",
        "wintitle_sold":           "Sold Licenses",
        "wintitle_col_pick":       "Pick Column",
        "wintitle_revoke":         "Revoke License",
        "wintitle_remove_lic":     "Remove License",
        "wintitle_lic_question":   "License",
        # Menubar
        "menu_about":              "About Continuity Bridge",
        "menu_prefs":              "Preferences…",
        "menu_quit":               "Quit Continuity Bridge",
        "menu_license":            "License…",
        "menu_remove_license":     "Remove License…",
        "menu_faq":                "FAQ…",
        "menu_check_updates":      "Check for Updates…",
        # Main screen section labels
        "section_ale":             "Avid Log Exchange file (ALE)",
        "section_pdf":             "Continuity Report (PDF)",
        "section_notes_col":       "Notes → column",
        # File widget
        "file_drop_hint":          "Drop files here or add…",
        "file_n_selected":         "{n} {word} selected",
        "file_word_single":        "file",
        "file_word_plural":        "files",
        "btn_choose":              "Choose…",
        # Hints
        "hint_more_settings":      "⚙  More settings in Preferences  (⌘,)",
        "btn_clear_all":           "↺  Clear All",
        "btn_process":             "✦  Process",
        "btn_busy":                "Processing…",
        # Preferences window
        "prefs_title":             "Preferences",
        "prefs_section_per_take":  "PER TAKE",
        "prefs_section_general":   "GENERAL NOTES PER SLATE",
        "prefs_notes":             "Notes",
        "prefs_scene":             "Scene",
        "prefs_rating":            "Rating",
        "prefs_stars_as":          "stars as:",
        "prefs_stars_stars":       "stars (***)",
        "prefs_stars_number":      "number (1-5)",
        "prefs_stars_letter":      "letters (X/V)",
        "prefs_write_pu":          "Write (PU)",
        "prefs_pu_own_col":        "PU in separate column",
        "prefs_pu_col_name":       "Column name",
        "prefs_write_afg":         "Write (AFG)",
        "prefs_position":          "position:",
        "prefs_pos_before":        "before",
        "prefs_pos_after":         "after",
        "prefs_sound_notes":       "Sound Notes",
        "prefs_camera_notes":      "Camera Notes",
        "prefs_opmerkingen":       "Notes",
        "prefs_output_dir":        "Output folder",
        "prefs_output_dir_hint":   "(empty = same folder as ALE)",
        "prefs_filename":          "Filename",
        "prefs_filename_orig":     "{original name}",
        "btn_close":               "Close",
        "btn_choose_dir":          "Choose…",
        "prefs_lang_label":        "Taal / Language / Sprache",
        "prefs_lang_restart_hint": "Restart the app to apply the language",
        # Log messages
        "log_ale_matched":         "ALE processed: {n} clips updated",
        "log_saved":               "Saved  —  {name}",
        "log_done_one":            "✓  Done  —  1 ALE file saved",
        "log_done_many":           "✓  Done  —  {n} ALE files saved",
        "ask_clear_title":         "Next shooting day?",
        "ask_clear_msg":           "Clear the fields for the next shooting day?",
        "btn_clear_yes":           "Clear",
        "btn_clear_no":            "Keep",
        "prefs_open_folder":       "Open folder after processing",
        "prefs_translit":          "Convert umlauts (ü→ue, ö→oe, ä→ae, ß→ss)",
        "prefs_ale_encoding":      "ALE encoding",
        "enc_auto":                "Auto (same as input)",
        "enc_utf8":                "UTF-8 (newer Avid)",
        "enc_macroman":            "Mac Roman (older Avid)",
        "prefs_ui_scale":          "Interface size",
        "prefs_ui_font":           "Font",
        "prefs_accent":            "Accent colour",
        "font_helvetica":          "Default",
        "font_systeem":            "System",
        "font_leesbaar":           "Readable",
        "prefs_section_appearance": "APPEARANCE",
        "prefs_section_output":    "OUTPUT",
        "prefs_section_language":  "LANGUAGE",
        "prefs_reset_scale":       "Reset (100%)",
        "prefs_clear_label":       "Clear after processing",
        "prefs_clear_delay":       "Delay",
        "clear_mode_uit":          "Off",
        "clear_mode_vragen":       "Ask",
        "clear_mode_auto":         "Automatic",
        "clear_delay_unit":        "sec",
        # Column picker
        "col_pick_search":         "Search:",
        "col_pick_own_label":      "Or type custom name:",
        "btn_cancel":              "Cancel",
        "btn_pick":                "Pick",
        "col_pick_placeholder":    "Choose column…",
        # Update dialog
        "update_available":        "Version {ver} available",
        "update_you_have":         "You have {ver}",
        "update_btn_install":      "Update & Restart",
        "update_btn_later":        "Later",
        "update_status_download":  "Downloading… {kb} KB",
        "update_status_install":   "Installing…",
        "update_status_done":      "Update complete!",
        "update_win_status_done":  "Installer started — follow the instructions.",
        "update_btn_restart":      "\U0001f504  Restart app",
        "update_error_prefix":     "Error: ",
        "update_no_update_msg":    "You already have the latest version ({ver}).",
        "update_fetch_error":      "Could not retrieve version info.\nCheck your internet connection or visit:\ngithub.com/{repo}/releases",
        # About window
        "about_version":           "Version {ver}",
        "about_author":            "by Michiel Boesveldt  © 2026",
        "btn_ok":                  "OK",
        # License dialog
        "lic_name_label":          "Name",
        "lic_serial_label":        "Serial number",
        "lic_btn_activate":        "Activate",
        "lic_btn_buy":             "\U0001f6d2  Buy License",
        "lic_buy_after":           "After payment you will receive the serial by email.",
        "lic_verify_msg":          "Verifying activation…",
        "lic_name_mismatch":       "✗ Name does not match the license.",
        "lic_already_bound":       "✗ Serial already activated on another machine.\nContact support@studiomichielboesveldt.nl",
        "lic_removed_msg":         "License removed. Enter a new serial number.",
        "lic_remove_confirm":      "Remove license from this Mac?\n\nYou will need to enter a new serial number afterwards.",
        "lic_ask_new_serial":      "Enter new serial number?",
        "lic_active_label":        "✓  Active",
        # License manager
        "mgr_token_label":         "GitHub manager token:",
        "mgr_btn_save_load":       "Save & load",
        "mgr_enter_token":         "Enter your GitHub manager token.",
        "mgr_loading":             "Loading…",
        "mgr_status_valid":        "Valid",
        "mgr_status_expired":      "Expired",
        "mgr_status_revoked":      "Revoked",
        "mgr_revoke_btn":          "⊘  Revoke selected license",
        "mgr_revoke_confirm":      "Revoke license for {naam}?\n\n{serial}\n\nThis cannot be undone.",
        "mgr_revoking":            "Revoking license…",
        "mgr_revoked_ok":          "Revoked: {serial}…",
        "mgr_revoke_err":          "Error revoking: {err}",
        "mgr_fetch_err":           "Error: {err}",
        # Layout mapper
        "layout_unknown_format":   "Unknown report format",
        "layout_hint":             "{fname}  —  indicate which column means what.",
        "layout_name_label":       "Name for this format:",
        "layout_no_take_col":      "Indicate at least the 'Take' column.",
        "btn_detect_process":      "Detect & process",
        "btn_skip":                "Skip",
        "field_ignore":            "— ignore —",
        "field_slate_scene":       "Slate / Scene",
        "field_take":              "Take",
        "field_note":              "Note / Comment",
        "field_rating":            "Rating (V/X)",
        "field_camera_roll":       "Camera roll",
        # File dialogs
        "dlg_pick_pdf":            "Choose PDF files",
        "dlg_pick_ale":            "Choose ALE files",
        "dlg_pick_dir":            "Choose output folder",
        # Run errors
        "err_no_license":          "No valid license. Activate via Continuity Bridge → License…",
        "err_no_pdf":              "Please choose one or more PDF files first.",
        "err_no_ale":              "Please choose one or more ALE files first.",
        # FAQ
        "faq_title":               "FAQ",
        "faq_subtitle":            "Frequently asked questions about Continuity Bridge",
        "faq_q1":  "How do I import the processed ALE back into Avid?",
        "faq_a1":  "In Avid go to Preferences → User → Import → Shot Log. "
                   "Under Events choose 'Merge events with known master clips'. "
                   "This way Avid adds the comments and ratings to your existing clips "
                   "instead of creating new ones.",
        "faq_q2":  "Which PDF formats are supported?",
        "faq_a2":  "Continuity Bridge supports most common continuity reports. "
                   "Does your report not work correctly? Report it via the bug form at "
                   "https://studiomichielboesveldt.nl/cbapp/feedback or email "
                   "support@studiomichielboesveldt.nl. We will take a look.",
        "faq_q3":  "Will my metadata disappear after creating a multiclip?",
        "faq_a3":  "It can. Always import the ALE before creating multiclips. "
                   "Avid does not automatically transfer metadata to existing multiclips.",
        "faq_q4":  "I get a warning that the app is from an unidentified developer.",
        "faq_a4":  "This is standard macOS security for apps outside the App Store. "
                   "Do NOT click 'Move to Trash'!\n\n"
                   "How to open the app:\n"
                   "1. Click 'Done' in the dialog\n"
                   "2. Open System Settings → Privacy & Security, scroll down\n"
                   "3. You'll see '\"Continuity Bridge\" was blocked…' → click 'Open Anyway'\n"
                   "4. Confirm once with Touch ID or your password\n\n"
                   "This is only needed once; macOS remembers it afterwards. Updates via "
                   "the in-app updater are not affected. We are working on an Apple "
                   "Developer registration to remove this warning entirely.",
        "faq_q5":  "Does Continuity Bridge work offline?",
        "faq_a5":  "Yes, fully. After activation the app needs no internet connection. "
                   "Processing happens locally on your Mac or PC.",
        "faq_q6":  "Can I use the license on multiple Macs?",
        "faq_a6":  "A license is tied to one machine. Moving to a new Mac? "
                   "Remove the license first via Help → Remove License, then activate "
                   "on your new Mac. Forgot? "
                   "Email support@studiomichielboesveldt.nl.",
        "faq_q7":  "What happens when my license expires?",
        "faq_a7":  "After one year the app stops processing until you renew. "
                   "Your files stay intact — nothing is deleted.",
        "faq_q8":  "My clips are not recognized. What now?",
        "faq_a8":  "Check that the clip names in your ALE match the names in the "
                   "continuity report. Small differences can cause a mismatch. "
                   "Still stuck? Report it via the bug form at "
                   "https://studiomichielboesveldt.nl/cbapp/feedback or email "
                   "support@studiomichielboesveldt.nl.",
        "faq_q9":  "On import Avid asks 'Tape name matches up to maximum length / Merge?'",
        "faq_a9":  "This is normal Avid behaviour, not an error. Just click 'Yes To All'.\n\n"
                   "Why it happens: Avid stores clip names with a maximum of 32 characters. "
                   "Drone clips have longer names (often 45+ characters). So the clip sits in "
                   "your bin under the shortened name, while the ALE contains the full name. Avid "
                   "sees that the first 32 characters match and asks, to be safe: is this the "
                   "same clip, merge?\n\n"
                   "Click 'Yes To All' = yes, it's the same clip. Your continuity data is then "
                   "linked correctly to the existing clips. Nothing is lost.\n\n"
                   "Continuity Bridge cannot remove this prompt: if it shortened the names to 32 "
                   "characters, Avid would no longer find the clips at all.",
        "faq_q10": "How do I export an ALE from Avid, and should 'UTF-8' be on?",
        "faq_a10": "Preferably export from a raw picture bin that still has the original camera "
                   "clip names. That gives the most reliable match. Select the clips (or the bin) "
                   "and choose File > Output > Export, with the format set to 'Avid Log Exchange "
                   "(ALE)'.\n\n"
                   "You can leave 'UTF-8 Encoding' on. Continuity Bridge reads both UTF-8 and the "
                   "older encoding, so it makes no difference.\n\n"
                   "Import the processed ALE back into that same picture bin (recommended). "
                   "Linked sync clips, subclips and scenes automatically inherit the added data "
                   "(rating, notes) from the master clips.\n\n"
                   "Tip: enable or create the columns you want to use (e.g. Rating, Take_notes, "
                   "Comment) in your Avid bin before exporting. They then already exist in the "
                   "ALE, so the data lands in the right columns straight after importing.",
    },
    "de": {
        # Fenstertitel
        "wintitle_main":           "Continuity Bridge",
        "wintitle_prefs":          "Einstellungen",
        "wintitle_faq":            "FAQ — Continuity Bridge",
        "wintitle_about":          "Über Continuity Bridge",
        "wintitle_license":        "Lizenz aktivieren",
        "wintitle_license_info":   "Lizenz",
        "wintitle_update":         "Update verfügbar",
        "wintitle_no_update":      "Keine Updates",
        "wintitle_update_check":   "Update-Prüfung",
        "wintitle_layout":         "Bericht erkennen",
        "wintitle_sold":           "Verkaufte Lizenzen",
        "wintitle_col_pick":       "Spalte wählen",
        "wintitle_revoke":         "Lizenz widerrufen",
        "wintitle_remove_lic":     "Lizenz entfernen",
        "wintitle_lic_question":   "Lizenz",
        # Menüleiste
        "menu_about":              "Über Continuity Bridge",
        "menu_prefs":              "Einstellungen…",
        "menu_quit":               "Continuity Bridge beenden",
        "menu_license":            "Lizenz…",
        "menu_remove_license":     "Lizenz entfernen…",
        "menu_faq":                "FAQ…",
        "menu_check_updates":      "Nach Updates suchen…",
        # Abschnittsbeschriftungen Hauptfenster
        "section_ale":             "Avid Log Exchange file (ALE)",
        "section_pdf":             "Kontinuitätsbericht (PDF)",
        "section_notes_col":       "Notizen → Spalte",
        # Datei-Widget
        "file_drop_hint":          "Dateien hierher ziehen oder hinzufügen…",
        "file_n_selected":         "{n} {word} ausgewählt",
        "file_word_single":        "Datei",
        "file_word_plural":        "Dateien",
        "btn_choose":              "Wählen…",
        # Hinweise
        "hint_more_settings":      "⚙  Weitere Einstellungen  (⌘,)",
        "btn_clear_all":           "↺  Alles löschen",
        "btn_process":             "✦  Verarbeiten",
        "btn_busy":                "Verarbeite…",
        # Einstellungsfenster
        "prefs_title":             "Einstellungen",
        "prefs_section_per_take":  "PRO TAKE",
        "prefs_section_general":   "ALLGEMEINE ANMERKUNGEN PRO SLATE",
        "prefs_notes":             "Notizen",
        "prefs_scene":             "Szene",
        "prefs_rating":            "Bewertung",
        "prefs_stars_as":          "Sterne als:",
        "prefs_stars_stars":       "Sterne (***)",
        "prefs_stars_number":      "Zahl (1-5)",
        "prefs_stars_letter":      "Buchstaben (X/V)",
        "prefs_write_pu":          "Schreibe (PU)",
        "prefs_pu_own_col":        "PU in eigener Spalte",
        "prefs_pu_col_name":       "Spaltenname",
        "prefs_write_afg":         "Schreibe (AFG)",
        "prefs_position":          "Position:",
        "prefs_pos_before":        "vor",
        "prefs_pos_after":         "nach",
        "prefs_sound_notes":       "Tonnotizen",
        "prefs_camera_notes":      "Kameranotizen",
        "prefs_opmerkingen":       "Anmerkungen",
        "prefs_output_dir":        "Ausgabeordner",
        "prefs_output_dir_hint":   "(leer = gleicher Ordner wie ALE)",
        "prefs_filename":          "Dateiname",
        "prefs_filename_orig":     "{originalname}",
        "btn_close":               "Schließen",
        "btn_choose_dir":          "Wählen…",
        "prefs_lang_label":        "Taal / Language / Sprache",
        "prefs_lang_restart_hint": "App neu starten um die Sprache zu übernehmen",
        # Log-Meldungen
        "log_ale_matched":         "ALE verarbeitet: {n} Clips aktualisiert",
        "log_saved":               "Gespeichert  —  {name}",
        "log_done_one":            "✓  Fertig  —  1 ALE-Datei gespeichert",
        "log_done_many":           "✓  Fertig  —  {n} ALE-Dateien gespeichert",
        "ask_clear_title":         "Nächster Drehtag?",
        "ask_clear_msg":           "Felder für den nächsten Drehtag leeren?",
        "btn_clear_yes":           "Leeren",
        "btn_clear_no":            "Behalten",
        "prefs_open_folder":       "Ordner nach Verarbeitung öffnen",
        "prefs_translit":          "Umlaute umwandeln (ü→ue, ö→oe, ä→ae, ß→ss)",
        "prefs_ale_encoding":      "ALE-Kodierung",
        "enc_auto":                "Auto (wie Eingabe)",
        "enc_utf8":                "UTF-8 (neueres Avid)",
        "enc_macroman":            "Mac Roman (älteres Avid)",
        "prefs_ui_scale":          "Oberflächengröße",
        "prefs_ui_font":           "Schriftart",
        "prefs_accent":            "Akzentfarbe",
        "font_helvetica":          "Standard",
        "font_systeem":            "System",
        "font_leesbaar":           "Lesbar",
        "prefs_section_appearance": "DARSTELLUNG",
        "prefs_section_output":    "AUSGABE",
        "prefs_section_language":  "SPRACHE",
        "prefs_reset_scale":       "Zurücksetzen (100%)",
        "prefs_clear_label":       "Nach Verarbeitung leeren",
        "prefs_clear_delay":       "Verzögerung",
        "clear_mode_uit":          "Aus",
        "clear_mode_vragen":       "Fragen",
        "clear_mode_auto":         "Automatisch",
        "clear_delay_unit":        "Sek",
        # Spaltenauswahl
        "col_pick_search":         "Suchen:",
        "col_pick_own_label":      "Oder eigenen Namen eingeben:",
        "btn_cancel":              "Abbrechen",
        "btn_pick":                "Wählen",
        "col_pick_placeholder":    "Spalte wählen…",
        # Update-Dialog
        "update_available":        "Version {ver} verfügbar",
        "update_you_have":         "Du hast {ver}",
        "update_btn_install":      "Update & Neustart",
        "update_btn_later":        "Später",
        "update_status_download":  "Herunterladen… {kb} KB",
        "update_status_install":   "Installieren…",
        "update_status_done":      "Update abgeschlossen!",
        "update_win_status_done":  "Installer gestartet — folge den Anweisungen.",
        "update_btn_restart":      "\U0001f504  App neu starten",
        "update_error_prefix":     "Fehler: ",
        "update_no_update_msg":    "Du hast bereits die neueste Version ({ver}).",
        "update_fetch_error":      "Versionsinformationen konnten nicht abgerufen werden.\nÜberprüfe deine Internetverbindung oder besuche:\ngithub.com/{repo}/releases",
        # Über-Fenster
        "about_version":           "Version {ver}",
        "about_author":            "von Michiel Boesveldt  © 2026",
        "btn_ok":                  "OK",
        # Lizenz-Dialog
        "lic_name_label":          "Name",
        "lic_serial_label":        "Seriennummer",
        "lic_btn_activate":        "Aktivieren",
        "lic_btn_buy":             "\U0001f6d2  Lizenz kaufen",
        "lic_buy_after":           "Nach der Zahlung erhältst du die Seriennummer per E-Mail.",
        "lic_verify_msg":          "Aktivierung wird überprüft…",
        "lic_name_mismatch":       "✗ Name stimmt nicht mit der Lizenz überein.",
        "lic_already_bound":       "✗ Seriennummer bereits auf einem anderen Gerät aktiviert.\nKontaktiere support@studiomichielboesveldt.nl",
        "lic_removed_msg":         "Lizenz entfernt. Gib eine neue Seriennummer ein.",
        "lic_remove_confirm":      "Lizenz von diesem Mac entfernen?\n\nDu musst danach eine neue Seriennummer eingeben.",
        "lic_ask_new_serial":      "Neue Seriennummer eingeben?",
        "lic_active_label":        "✓  Aktiv",
        # Lizenzverwaltung
        "mgr_token_label":         "GitHub-Manager-Token:",
        "mgr_btn_save_load":       "Speichern & laden",
        "mgr_enter_token":         "GitHub-Manager-Token eingeben.",
        "mgr_loading":             "Lade…",
        "mgr_status_valid":        "Gültig",
        "mgr_status_expired":      "Abgelaufen",
        "mgr_status_revoked":      "Widerrufen",
        "mgr_revoke_btn":          "⊘  Ausgewählte Lizenz widerrufen",
        "mgr_revoke_confirm":      "Lizenz von {naam} widerrufen?\n\n{serial}\n\nDies kann nicht rückgängig gemacht werden.",
        "mgr_revoking":            "Lizenz wird widerrufen…",
        "mgr_revoked_ok":          "Widerrufen: {serial}…",
        "mgr_revoke_err":          "Fehler beim Widerrufen: {err}",
        "mgr_fetch_err":           "Fehler: {err}",
        # Layout-Mapper
        "layout_unknown_format":   "Unbekanntes Berichtsformat",
        "layout_hint":             "{fname}  —  weise an, welche Spalte was bedeutet.",
        "layout_name_label":       "Name für dieses Format:",
        "layout_no_take_col":      "Weise mindestens die Spalte 'Take' an.",
        "btn_detect_process":      "Erkennen & verarbeiten",
        "btn_skip":                "Überspringen",
        "field_ignore":            "— ignorieren —",
        "field_slate_scene":       "Slate / Scene",
        "field_take":              "Take",
        "field_note":              "Anmerkung / Notiz",
        "field_rating":            "Bewertung (V/X)",
        "field_camera_roll":       "Kamerarolle",
        # Dateidialoge
        "dlg_pick_pdf":            "PDF-Dateien wählen",
        "dlg_pick_ale":            "ALE-Dateien wählen",
        "dlg_pick_dir":            "Ausgabeordner wählen",
        # Laufzeitfehler
        "err_no_license":          "Keine gültige Lizenz. Aktiviere über Continuity Bridge → Lizenz…",
        "err_no_pdf":              "Bitte zuerst eine oder mehrere PDF-Dateien auswählen.",
        "err_no_ale":              "Bitte zuerst eine oder mehrere ALE-Dateien auswählen.",
        # FAQ
        "faq_title":               "FAQ",
        "faq_subtitle":            "Häufig gestellte Fragen zu Continuity Bridge",
        "faq_q1":  "Wie importiere ich das verarbeitete ALE zurück in Avid?",
        "faq_a1":  "Gehe in Avid zu Preferences → User → Import → Shot Log. "
                   "Wähle unter Events die Option 'Merge events with known master clips'. "
                   "So fügt Avid die Kommentare und Bewertungen zu deinen vorhandenen Clips hinzu "
                   "anstatt neue Clips zu erstellen.",
        "faq_q2":  "Welche PDF-Formate werden unterstützt?",
        "faq_a2":  "Continuity Bridge unterstützt die meisten gängigen Kontinuitätsberichte. "
                   "Funktioniert dein Bericht nicht richtig? Melde es ueber das Bug-Formular auf "
                   "https://studiomichielboesveldt.nl/cbapp/feedback oder schreibe an "
                   "support@studiomichielboesveldt.nl. Wir schauen uns das an.",
        "faq_q3":  "Verschwinden meine Metadaten nach dem Erstellen eines Multiclips?",
        "faq_a3":  "Das kann passieren. Importiere das ALE immer bevor du Multiclips erstellst. "
                   "Avid überträgt Metadaten nicht automatisch auf vorhandene Multiclips.",
        "faq_q4":  "Ich erhalte eine Warnung, dass die App von einem unbekannten Entwickler stammt.",
        "faq_a4":  "Dies ist die Standard-macOS-Sicherheitsfunktion für Apps außerhalb des App Stores. "
                   "Klicke NICHT auf 'In den Papierkorb legen'!\n\n"
                   "So öffnest du die App:\n"
                   "1. Klicke im Dialog auf 'Fertig' (Done)\n"
                   "2. Öffne Systemeinstellungen → Datenschutz & Sicherheit, scrolle nach unten\n"
                   "3. Dort steht '\"Continuity Bridge\" wurde blockiert…' → klicke 'Dennoch öffnen'\n"
                   "4. Bestätige einmalig mit Touch ID oder deinem Passwort\n\n"
                   "Das ist nur einmal nötig; danach merkt sich macOS die Entscheidung. "
                   "Updates über den In-App-Updater sind nicht betroffen. Wir arbeiten an "
                   "einer Apple-Developer-Registrierung, damit diese Meldung ganz verschwindet.",
        "faq_q5":  "Funktioniert Continuity Bridge offline?",
        "faq_a5":  "Ja, vollständig. Nach der Aktivierung benötigt die App keine Internetverbindung. "
                   "Die Verarbeitung erfolgt lokal auf deinem Mac oder PC.",
        "faq_q6":  "Kann ich die Lizenz auf mehreren Macs verwenden?",
        "faq_a6":  "Eine Lizenz ist an ein Gerät gebunden. Wechselst du zu einem neuen Mac? "
                   "Entferne die Lizenz zuerst über Hilfe → Lizenz entfernen, und aktiviere "
                   "dann auf deinem neuen Mac. Vergessen? "
                   "Schreib an support@studiomichielboesveldt.nl.",
        "faq_q7":  "Was passiert, wenn meine Lizenz abläuft?",
        "faq_a7":  "Nach einem Jahr stoppt die App mit der Verarbeitung bis du verlängerst. "
                   "Deine Dateien bleiben unberührt — es wird nichts gelöscht.",
        "faq_q8":  "Meine Clips werden nicht erkannt. Was nun?",
        "faq_a8":  "Überprüfe, ob die Clip-Namen in deinem ALE mit den Namen im "
                   "Kontinuitätsbericht übereinstimmen. Kleine Abweichungen können zu Nichtübereinstimmungen führen. "
                   "Klappt es nicht? Melde es ueber das Bug-Formular auf "
                   "https://studiomichielboesveldt.nl/cbapp/feedback oder schreibe an "
                   "support@studiomichielboesveldt.nl.",
        "faq_q9":  "Avid fragt beim Import 'Tape name matches up to maximum length / Merge?'",
        "faq_a9":  "Das ist normales Avid-Verhalten, kein Fehler. Klicke einfach auf 'Yes To All'.\n\n"
                   "Warum es passiert: Avid speichert Clip-Namen mit maximal 32 Zeichen. "
                   "Drohnen-Clips haben laengere Namen (oft 45+ Zeichen). Der Clip liegt also im "
                   "Bin unter dem gekuerzten Namen, waehrend das ALE den vollstaendigen Namen "
                   "enthaelt. Avid sieht, dass die ersten 32 Zeichen gleich sind, und fragt "
                   "sicherheitshalber: ist das derselbe Clip, zusammenfuehren?\n\n"
                   "Klicke 'Yes To All' = ja, es ist derselbe Clip. Deine Kontinuitaetsdaten "
                   "werden dann korrekt mit den vorhandenen Clips verknuepft. Es geht nichts "
                   "verloren.\n\n"
                   "Continuity Bridge kann diese Frage nicht entfernen: wuerde es die Namen auf "
                   "32 Zeichen kuerzen, wuerde Avid die Clips gar nicht mehr finden.",
        "faq_q10": "Wie exportiere ich ein ALE aus Avid, und sollte 'UTF-8' an sein?",
        "faq_a10": "Exportiere am besten aus einem rohen Bild-Bin mit den originalen "
                   "Kamera-Clip-Namen. Das ergibt die zuverlaessigste Zuordnung. Waehle die Clips "
                   "(oder den Bin) und gehe auf File > Output > Export, mit dem Format 'Avid Log "
                   "Exchange (ALE)'.\n\n"
                   "Die Option 'UTF-8 Encoding' kann ruhig an bleiben. Continuity Bridge liest "
                   "sowohl UTF-8 als auch die aeltere Kodierung, es macht also keinen "
                   "Unterschied.\n\n"
                   "Importiere das verarbeitete ALE wieder in denselben Bild-Bin (empfohlen). "
                   "Verknuepfte Sync-Clips, Subclips und Szenen uebernehmen die hinzugefuegten "
                   "Daten (Bewertung, Notizen) automatisch von den Masterclips.\n\n"
                   "Tipp: aktiviere oder erstelle in deinem Avid-Bin schon die gewuenschten "
                   "Spalten (z.B. Rating, Take_notes, Comment), bevor du exportierst. Dann "
                   "existieren sie bereits im ALE und die Daten landen nach dem Import direkt in "
                   "den richtigen Spalten.",
    },
}

# Module-level _prefs placeholder so t() can reference it before _load_prefs runs
_prefs: dict = {}


def t(key: str, **kwargs) -> str:
    """Return translated string for current language, fallback to NL."""
    lang = _prefs.get("language", "en") if _prefs else "en"
    s = STRINGS.get(lang, STRINGS["nl"]).get(key) or STRINGS["nl"].get(key, f"[{key}]")
    return s.format(**kwargs) if kwargs else s

# ── End vertalingen ────────────────────────────────────────────────────────────

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
MUTED    = "#9C8FD0"   # gedempte subtekst (lichter voor leesbaarheid)
AVID_B   = "#8B30F5"   # elektrisch paars (knop, header) — accentkleur, instelbaar
AVID_B_H = "#7A26E0"   # hover — iets donkerder
ACCENT2  = "#B98CFF"   # lichter paars accent (FAQ-plus, kolomlabels)
SUCCESS  = "#4ED98A"
ERROR    = "#FF5577"

# Lettertypes — instelbaar via Voorkeuren (worden bij opstart uit prefs gezet)
UI_FONT   = "Helvetica Neue"   # hoofd-UI-lettertype
MONO_FONT = "Menlo"            # monospace (logvenster)

# Lettertype-keuzes → family. "Leesbaar" gebruikt een breed beschikbaar leesbaar font.
UI_FONT_CHOICES = {
    "helvetica": "Helvetica Neue",
    "systeem":   ".AppleSystemUIFont",
    "leesbaar":  "Verdana",
}

def _apply_font(code):
    """Zet het globale UI-lettertype op basis van keuze."""
    global UI_FONT
    fam = UI_FONT_CHOICES.get(code)
    if fam:
        UI_FONT = fam

# Accentkleur-thema's: (basis, hover, licht-accent)
ACCENT_THEMES = {
    "paars":  ("#8B30F5", "#7A26E0", "#B98CFF"),
    "blauw":  ("#2F6FED", "#255CC8", "#8FB4FF"),
    "groen":  ("#16A46B", "#128456", "#7FE3B5"),
    "roze":   ("#E5439B", "#C4327F", "#FF9CD1"),
    "oranje": ("#E8722A", "#C85E20", "#FFB483"),
}

def _apply_accent(code):
    """Zet de globale accentkleuren op basis van themakeuze."""
    global AVID_B, AVID_B_H, ACCENT2
    trio = ACCENT_THEMES.get(code)
    if trio:
        AVID_B, AVID_B_H, ACCENT2 = trio


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
# ---------------------------------------------------------------------------
# AANGEPASTE RAPPORT-LAYOUTS  (opslaan in ~/.continuitybridge/layouts.json)
# ---------------------------------------------------------------------------
import json as _json_layouts

_LAYOUTS_FILE = Path.home() / ".continuitybridge" / "layouts.json"

def _load_layouts():
    try:
        return _json_layouts.loads(_LAYOUTS_FILE.read_text())
    except Exception:
        return []

def _save_layout(entry):
    layouts = _load_layouts()
    # vervang bestaand met dezelfde fingerprint
    layouts = [l for l in layouts if l.get("fingerprint") != entry["fingerprint"]]
    layouts.append(entry)
    _LAYOUTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAYOUTS_FILE.write_text(_json_layouts.dumps(layouts, indent=2))

def _fingerprint_table(headers):
    """Stabiele fingerprint op basis van kolomkoppen."""
    return "|".join(sorted(h.strip() for h in headers if h and h.strip()))

def _find_layout(headers):
    """Geeft opgeslagen layout terug als fingerprint matcht, anders None."""
    fp = _fingerprint_table(headers)
    for l in _load_layouts():
        if l.get("fingerprint") == fp:
            return l
    return None

def _parse_pdf_custom(pdf_path, layout, log):
    """Parseer PDF aan de hand van een opgeslagen kolomtoewijzing."""
    mapping  = layout.get("mapping", {})
    col_take = mapping.get("take")
    col_note = mapping.get("note")
    col_rate = mapping.get("rating")
    col_slat = mapping.get("slate")
    col_roll = mapping.get("camera_roll")
    clips    = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables():
                if not tbl or len(tbl) < 2:
                    continue
                headers = [str(c or "").strip() for c in tbl[0]]
                fp = _fingerprint_table(headers)
                if fp != layout.get("fingerprint"):
                    continue

                def ci(col):
                    if col and col in headers:
                        return headers.index(col)
                    return None

                ti = ci(col_take); ni = ci(col_note)
                ri = ci(col_rate); si = ci(col_slat)
                roi = ci(col_roll)

                for row in tbl[1:]:
                    def cell(idx):
                        if idx is None or idx >= len(row):
                            return ""
                        return str(row[idx] or "").strip()

                    take  = cell(ti)
                    note  = cell(ni)
                    rate  = cell(ri)
                    slate = cell(si)
                    roll  = cell(roi)

                    if not take:
                        continue

                    key = f"{slate}-{take.zfill(2)}" if slate else take.zfill(2)
                    clips[key] = {
                        "circle":     rate,
                        "scene":      slate,
                        "description": "",
                        "take_notes": note,
                    }
                    if roll:
                        clips[key]["camera_roll"] = roll

    if clips:
        log(f"Aangepaste layout '{layout.get('name','?')}': "
            f"{len(clips)} clip(s) herkend.", "info")
    return clips


# ---------------------------------------------------------------------------
# VOORKEUREN  (opslaan in ~/.continuitybridge/prefs.json)
# ---------------------------------------------------------------------------
import json as _json_prefs

_PREFS_DIR  = Path.home() / ".continuitybridge"
_PREFS_FILE = _PREFS_DIR / "prefs.json"

_PREFS_DEFAULTS = {
    "write_rating":       False,
    "rating_col":         "Auto",
    "star_format":        "sterren",
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
    "pu_eigen_kolom":     False,
    "pu_eigen_kolom_naam": "PU",
    "afg_col":            "Auto",
    "afg_position":       "voor",
    "write_general_notes": False,
    "general_notes_col":  "Camera_Notes",
    "write_scene":        True,
    "scene_col":          "Auto",
    "language":           "en",
    "clear_mode":         "vragen",   # "uit" | "vragen" | "automatisch"
    "clear_delay":        5,          # seconden, in stappen van 5
    "open_folder_after":  True,       # map met resultaat openen na verwerken
    "translit_umlauts":   False,      # ü→ue, ö→oe, ä→ae, ß→ss bij export
    "ale_encoding":       "auto",     # auto (zoals invoer) | utf-8 | mac_roman
    "ui_scale":           100,        # interfacegrootte in % (90–150)
    "ui_font":            "helvetica", # helvetica | systeem | leesbaar
    "accent":            "paars",     # paars | blauw | groen | roze | oranje
}
_INVALID_COL_VALUES = {"Kies kolom…", "Choose column…", "Spalte wählen…",
                       "Eigen naam…", "Kies kolom...", ""}

def _load_prefs():
    global _prefs
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
            _prefs = prefs
            return prefs
    except Exception:
        pass
    _prefs = dict(_PREFS_DEFAULTS)
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
                    "Note", "Notes", "Take_notes"]
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

        # Uiterlijk toepassen vóór de widgets gebouwd worden: lettertype + accentkleur.
        _apply_font(_p.get("ui_font", "helvetica"))
        _apply_accent(_p.get("accent", "paars"))
        self._prev_accent = _p.get("accent", "paars")

        # UI-schaal: we schalen fonts DIRECT (per widget), niet via tk scaling —
        # dat werkt betrouwbaar op macOS én neemt de dropdowns/comboboxen mee.
        self._font_base = {}   # widget-pad → (basisgrootte, weight, slant)
        self._ui_scale_pct = int(_p.get("ui_scale", 100) or 100)
        self._ui_scale_pct = max(10, min(200, self._ui_scale_pct))
        self._scale = self._ui_scale_pct / 100.0
        _factor = self._scale
        self._win_w = int(520 * _factor)
        self._win_h = int(650 * _factor)

        self.write_rating     = tk.BooleanVar(value=_p["write_rating"])
        self.star_format      = tk.StringVar(value=_p.get("star_format", "sterren"))
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
        self.pu_eigen_kolom     = tk.BooleanVar(value=_p.get("pu_eigen_kolom", False))
        self.pu_eigen_kolom_naam = tk.StringVar(value=_p.get("pu_eigen_kolom_naam", "PU"))
        self.afg_col            = tk.StringVar(value=_p.get("afg_col", "Auto"))
        self.afg_position       = tk.StringVar(value=_p.get("afg_position", "voor"))
        self.write_general_notes = tk.BooleanVar(value=_p.get("write_general_notes", False))
        self.general_notes_col  = tk.StringVar(value=_p.get("general_notes_col", "Camera_Notes"))
        self.write_scene        = tk.BooleanVar(value=_p.get("write_scene", True))
        self.scene_col          = tk.StringVar(value=_p.get("scene_col", "Auto"))
        self.language           = tk.StringVar(value=_p.get("language", "en"))
        self.clear_mode         = tk.StringVar(value=_p.get("clear_mode", "vragen"))
        self.clear_delay        = tk.IntVar(value=_p.get("clear_delay", 5))
        self.open_folder_after  = tk.BooleanVar(value=_p.get("open_folder_after", True))
        self.translit_umlauts   = tk.BooleanVar(value=_p.get("translit_umlauts", False))
        self.ale_encoding       = tk.StringVar(value=_p.get("ale_encoding", "auto"))
        self.ui_scale           = tk.IntVar(value=self._ui_scale_pct)
        self.ui_font            = tk.StringVar(value=_p.get("ui_font", "helvetica"))
        self.accent             = tk.StringVar(value=_p.get("accent", "paars"))
        self._prefs_cache = _p   # bewaar voor recents

        def _save_all():
            _save_prefs({
                "write_rating":       self.write_rating.get(),
                "rating_col":         self.rating_col.get(),
                "star_format":        self.star_format.get(),
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
                "pu_eigen_kolom":     self.pu_eigen_kolom.get(),
                "pu_eigen_kolom_naam": self.pu_eigen_kolom_naam.get(),
                "afg_col":            self.afg_col.get(),
                "afg_position":       self.afg_position.get(),
                "write_general_notes": self.write_general_notes.get(),
                "general_notes_col":  self.general_notes_col.get(),
                "write_scene":        self.write_scene.get(),
                "scene_col":          self.scene_col.get(),
                "language":           self.language.get(),
                "clear_mode":         self.clear_mode.get(),
                "clear_delay":        self.clear_delay.get(),
                "open_folder_after":  self.open_folder_after.get(),
                "translit_umlauts":   self.translit_umlauts.get(),
                "ale_encoding":       self.ale_encoding.get(),
                "ui_scale":           self.ui_scale.get(),
                "ui_font":            self.ui_font.get(),
                "accent":             self.accent.get(),
            })
        self._save_prefs_all = _save_all

        # Sla prefs op bij elke wijziging (maar sla geen placeholders op)
        def _on_pref_change(*_):
            if self.rating_col.get() in _INVALID_COL_VALUES: return
            if self.notes_col.get()  in _INVALID_COL_VALUES: return
            _save_all()
        self.write_rating    .trace_add("write", _on_pref_change)
        self.star_format     .trace_add("write", _on_pref_change)
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
        self.pu_eigen_kolom    .trace_add("write", _on_pref_change)
        self.pu_eigen_kolom_naam.trace_add("write", _on_pref_change)
        self.afg_col           .trace_add("write", _on_pref_change)
        self.afg_position      .trace_add("write", _on_pref_change)
        self.write_general_notes.trace_add("write", _on_pref_change)
        self.general_notes_col .trace_add("write", _on_pref_change)
        self.write_scene       .trace_add("write", _on_pref_change)
        self.scene_col         .trace_add("write", _on_pref_change)
        self.clear_mode.trace_add("write", _on_pref_change)
        self.clear_delay.trace_add("write", _on_pref_change)
        self.open_folder_after.trace_add("write", _on_pref_change)
        self.translit_umlauts.trace_add("write", _on_pref_change)
        self.ale_encoding.trace_add("write", _on_pref_change)
        self.ui_scale.trace_add("write", _on_pref_change)
        self.ui_font.trace_add("write", _on_pref_change)
        self.accent.trace_add("write", _on_pref_change)
        self.root.title(t("wintitle_main"))
        self.root.geometry(f"{self._win_w}x{self._win_h}")
        self.root.resizable(False, True)
        self.root.minsize(520, 520)
        self.root.configure(bg=BG)

        # ── Update-check ─────────────────────────────────────────────────────
        def _check_updates(silent=False):
            """Check GitHub releases. silent=True → alleen tonen bij nieuwere versie."""
            import urllib.request, json as _json2, ssl as _ssl
            def _do():
                try:
                    # SSL context: certifi → systeemcerts → unverified
                    def _make_ctx():
                        try:
                            import certifi as _certifi
                            return _ssl.create_default_context(cafile=_certifi.where())
                        except Exception:
                            pass
                        try:
                            return _ssl.create_default_context()
                        except Exception:
                            return _ssl._create_unverified_context()
                    req = urllib.request.Request(RELEASES_URL,
                          headers={"User-Agent": "ContinuityBridge"})
                    with urllib.request.urlopen(req, timeout=10, context=_make_ctx()) as r:
                        releases = _json2.loads(r.read())
                    if not isinstance(releases, list) or not releases:
                        if not silent:
                            self.root.after(0, lambda: tk.messagebox.showinfo(
                                t("wintitle_no_update"),
                                t("update_no_update_msg", ver=VERSION)))
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
                            want = '.exe'
                        elif _plat.machine() == 'arm64':
                            want = 'Silicon'
                        else:
                            want = 'Intel'
                        asset = next((a for a in assets if want in a['name']), None)
                        dl_url = asset['browser_download_url'] if asset else None
                        self.root.after(0, lambda lv=latest, url=dl_url:
                                        _show_update_dialog(lv, url))
                    elif not silent:
                        self.root.after(0, lambda: tk.messagebox.showinfo(
                            t("wintitle_no_update"),
                            t("update_no_update_msg", ver=VERSION)))
                except Exception:
                    if not silent:
                        self.root.after(0, lambda: tk.messagebox.showinfo(
                            t("wintitle_update_check"),
                            t("update_fetch_error", repo=GITHUB_REPO)))
            threading.Thread(target=_do, daemon=True).start()

        def _show_update_dialog(latest_version, dl_url):
            """In-app update dialog met progress bar en automatische herstart."""
            import webbrowser as _wb
            dlg = tk.Toplevel(self.root)
            dlg.title(t("wintitle_update"))
            dlg.configure(bg=BG)
            dlg.resizable(False, False)
            dlg.geometry("420x230")
            dlg.grab_set()

            tk.Label(dlg, text=t("update_available", ver=latest_version),
                     bg=BG, fg=TEXT, font=(UI_FONT, 14, "bold")).pack(pady=(24, 4))
            tk.Label(dlg, text=t("update_you_have", ver=VERSION),
                     bg=BG, fg=MUTED, font=(UI_FONT, 11)).pack()

            prog_frame = tk.Frame(dlg, bg=BG)
            prog_frame.pack(fill="x", padx=36, pady=(18, 4))
            prog = ttk.Progressbar(prog_frame, length=348, mode='determinate')
            prog.pack()

            status_lbl = tk.Label(dlg, text="", bg=BG, fg=MUTED,
                                  font=(UI_FONT, 10))
            status_lbl.pack(pady=(0, 12))

            btn_frame = tk.Frame(dlg, bg=BG)
            btn_frame.pack()

            def _fallback():
                _wb.open(RELEASES_PAGE); dlg.destroy()

            # Gedeelde status: de downloadthread schrijft hier ALLEEN platte
            # waarden in; de hoofdthread pollt en werkt de UI bij. (Tkinter
            # aanroepen vanuit een tweede thread kan deadlocken → beachball.)
            _ustate = {"pct": 0.0, "kb": 0, "phase": "idle",
                       "done": None, "error": None, "win_done": False}

            def _poll():
                try:
                    if _ustate["error"] is not None:
                        _on_error(_ustate["error"]); return
                    if _ustate["win_done"]:
                        _finish_win(); return
                    if _ustate["done"] is not None:
                        _finish_mac(*_ustate["done"]); return
                    prog.config(value=_ustate["pct"])
                    if _ustate["phase"] == "download":
                        status_lbl.config(text=t("update_status_download",
                                                 kb=_ustate["kb"]))
                    elif _ustate["phase"] == "install":
                        status_lbl.config(text=t("update_status_install"))
                    dlg.after(120, _poll)
                except tk.TclError:
                    pass   # dialoog gesloten

            def _start():
                if not dl_url:
                    _fallback(); return
                upd_cv.config(cursor="wait")
                upd_cv.unbind("<Button-1>")
                later_cv.config(cursor="arrow")
                later_cv.unbind("<Button-1>")
                threading.Thread(target=_download_and_install, daemon=True).start()
                dlg.after(120, _poll)

            def _ulog(msg):
                try:
                    import os as _o, time as _tm
                    p = _o.path.expanduser("~/Library/Logs/ContinuityBridge-update.log")
                    _o.makedirs(_o.path.dirname(p), exist_ok=True)
                    with open(p, "a") as _f:
                        _f.write(f"{_tm.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
                except Exception:
                    pass

            def _download_and_install():
                import urllib.request as _ur2, tempfile, os, sys as _sys3, ssl as _ssl2
                _ulog(f"download start: {dl_url}")
                try:
                    try:
                        import certifi as _certifi2
                        _ctx2 = _ssl2.create_default_context(cafile=_certifi2.where())
                    except Exception:
                        try:
                            _ctx2 = _ssl2.create_default_context()
                        except Exception:
                            _ctx2 = _ssl2._create_unverified_context()
                    # ── Download ──────────────────────────────────────────────
                    # Geen tkinter-aanroepen vanuit deze thread! Alleen _ustate
                    # bijwerken; de hoofdthread pollt en tekent.
                    ext = '.exe' if _sys3.platform == 'win32' else '.dmg'
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    _ustate["phase"] = "download"
                    with _ur2.urlopen(dl_url, timeout=120, context=_ctx2) as resp:
                        total = int(resp.headers.get('Content-Length', 0))
                        done  = 0
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            tmp.write(chunk)
                            done += len(chunk)
                            _ustate["kb"] = done // 1024
                            if total:
                                _ustate["pct"] = done / total * 100
                    tmp.close()
                    tmp_path = tmp.name
                    _ulog(f"download klaar: {done} bytes -> {tmp_path}")
                    _ustate["phase"] = "install"

                    if _sys3.platform == 'win32':
                        import subprocess as _sp3
                        _sp3.Popen([tmp_path], shell=True)
                        _ustate["win_done"] = True
                    else:
                        import subprocess as _sp3, glob, shutil
                        # Mount DMG. LET OP: géén -quiet — die onderdrukt óók de
                        # mount-tabel in stdout, waardoor het mount-pad nooit te
                        # parsen valt ("DMG mounten mislukt").
                        r = _sp3.run(
                            ['hdiutil', 'attach', '-nobrowse',
                             '-noverify', tmp_path],
                            capture_output=True, text=True)
                        mount_pt = None
                        for line in r.stdout.strip().splitlines():
                            parts = line.split('\t')
                            if len(parts) >= 3 and '/Volumes/' in parts[-1]:
                                mount_pt = parts[-1].strip()
                        if not mount_pt:
                            raise RuntimeError("DMG mounten mislukt")
                        _ulog(f"DMG gemount op {mount_pt}")
                        apps = glob.glob(os.path.join(mount_pt, '*.app'))
                        if not apps:
                            raise RuntimeError("Geen .app in DMG")
                        new_app = apps[0]

                        # Bepaal het pad van de huidige (draaiende) .app
                        if getattr(_sys3, 'frozen', False):
                            install_path = str(Path(_sys3.executable).parents[2])
                        else:
                            install_path = f"/Applications/{os.path.basename(new_app)}"

                        # Kopieer de nieuwe app NAAR een temp-map (niet over de
                        # draaiende app heen). Het vervangen gebeurt straks via een
                        # helper-script dat wacht tot de app gesloten is.
                        stage_dir = tempfile.mkdtemp(prefix="cb_update_")
                        staged_app = os.path.join(stage_dir, os.path.basename(new_app))
                        shutil.copytree(new_app, staged_app)
                        _sp3.run(['hdiutil', 'detach', '-quiet', mount_pt],
                                 capture_output=True)
                        os.unlink(tmp_path)
                        _ulog(f"gestaged naar {staged_app}; doelpad {install_path}")
                        _ustate["done"] = (install_path, staged_app, stage_dir)

                except Exception as exc:
                    _ulog(f"FOUT tijdens download/install: {exc!r}")
                    _ustate["error"] = str(exc)

            def _finish_mac(install_path, staged_app, stage_dir):
                prog.config(value=100)
                status_lbl.config(fg=SUCCESS, text=t("update_status_done"))
                upd_cv.pack_forget()
                later_cv.pack_forget()
                rst = _rounded_btn(btn_frame, t("update_btn_restart"),
                                   lambda: _do_restart(install_path, staged_app, stage_dir),
                                   bg=AVID_B, hv=AVID_B_H, fg="white",
                                   font=(UI_FONT, 11, "bold"),
                                   px=20, py=7, r=10, pbg=BG)
                rst.pack(side="left", padx=(0, 10))
                lat = _rounded_btn(btn_frame, t("update_btn_later"), dlg.destroy,
                                   bg=SURFACE2, hv=BORDER, fg=MUTED,
                                   font=(UI_FONT, 11),
                                   px=16, py=7, r=10, pbg=BG)
                lat.pack(side="left")

            def _finish_win():
                prog.config(value=100)
                status_lbl.config(fg=SUCCESS, text=t("update_win_status_done"))
                later_cv.config(state="normal")

            def _do_restart(install_path, staged_app, stage_dir):
                # Helper-script wacht tot deze app dicht is, vervangt dan de oude
                # .app door de nieuwe, verwijdert quarantine en herstart.
                import subprocess as _sp4, sys as _sys4, os as _os4, shlex as _shlex4
                _q = _shlex4.quote
                pid = _os4.getpid()
                script = _os4.path.join(stage_dir, "cb_update.sh")
                _logf = _os4.path.expanduser("~/Library/Logs/ContinuityBridge-update.log")
                sh = f'''#!/bin/bash
APP={_q(install_path)}
NEW={_q(staged_app)}
STAGE={_q(stage_dir)}
LOG={_q(_logf)}
mkdir -p "$(dirname "$LOG")"
echo "=== $(date) update-helper gestart (pid {pid}) ===" >> "$LOG"
echo "APP=$APP" >> "$LOG"; echo "NEW=$NEW" >> "$LOG"
# wacht tot de huidige app gesloten is
while kill -0 {pid} 2>/dev/null; do sleep 0.3; done
sleep 0.4
rm -rf "$APP" 2>>"$LOG"
/usr/bin/ditto "$NEW" "$APP" 2>>"$LOG"
echo "ditto exit=$?" >> "$LOG"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
open "$APP" 2>>"$LOG"
echo "open exit=$? — klaar" >> "$LOG"
rm -rf "$STAGE"
'''
                with open(script, "w") as _f:
                    _f.write(sh)
                _os4.chmod(script, 0o755)
                _sp4.Popen(['/bin/bash', script], start_new_session=True)
                _sys4.exit(0)

            def _on_error(err):
                status_lbl.config(fg=ERROR, text=t("update_error_prefix") + err[:60])
                upd_cv.config(cursor="hand2")
                upd_cv.bind("<Button-1>", lambda e: _start())
                later_cv.config(cursor="hand2")
                later_cv.bind("<Button-1>", lambda e: dlg.destroy())

            upd_cv = _rounded_btn(btn_frame, t("update_btn_install"), _start,
                                   bg=AVID_B, hv=AVID_B_H, fg="white",
                                   font=(UI_FONT, 11, "bold"),
                                   px=20, py=7, r=10, pbg=BG)
            upd_cv.pack(side="left", padx=(0, 10))
            later_cv = _rounded_btn(btn_frame, t("update_btn_later"), dlg.destroy,
                                    bg=SURFACE2, hv=BORDER, fg=MUTED,
                                    font=(UI_FONT, 11),
                                    px=16, py=7, r=10, pbg=BG)
            later_cv.pack(side="left")

        # ── Layout Mapper ────────────────────────────────────────────────────
        def _show_layout_mapper(pdf_path, on_done):
            """Toon dialoog voor onbekend rapport-formaat. on_done(clips|None)."""
            import pdfplumber as _plb

            # Haal eerste tabel op
            sample_headers = []
            sample_rows    = []
            try:
                with _plb.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        for tbl in page.extract_tables():
                            if tbl and len(tbl) >= 2:
                                sample_headers = [str(c or "").strip() for c in tbl[0]]
                                sample_rows    = [[str(c or "").strip() for c in r]
                                                  for r in tbl[1:6]]
                                break
                        if sample_headers:
                            break
            except Exception:
                pass

            if not sample_headers:
                self.log("Rapport niet herkend en geen tabel gevonden in PDF.", "warn")
                on_done(None)
                return

            dlg = tk.Toplevel(self.root)
            dlg.title(t("wintitle_layout"))
            dlg.configure(bg=BG)
            dlg.resizable(True, True)
            dlg.geometry("680x560")
            dlg.grab_set()

            import os as _os2
            fname = _os2.path.basename(pdf_path)
            tk.Label(dlg, text=t("layout_unknown_format"),
                     bg=BG, fg=TEXT, font=(UI_FONT, 14, "bold")).pack(
                anchor="w", padx=24, pady=(20, 2))
            tk.Label(dlg, text=t("layout_hint", fname=fname),
                     bg=BG, fg=MUTED, font=(UI_FONT, 11)).pack(
                anchor="w", padx=24, pady=(0, 14))

            # Tabel preview
            tbl_frame = tk.Frame(dlg, bg=SURFACE2,
                                 highlightbackground=BORDER, highlightthickness=1)
            tbl_frame.pack(fill="x", padx=24, pady=(0, 16))

            FIELD_OPTIONS = [t("field_ignore"), t("field_slate_scene"), t("field_take"),
                             t("field_note"), t("field_rating"), t("field_camera_roll")]

            col_vars = []  # StringVar per kolom
            for ci2, hdr in enumerate(sample_headers):
                col_f = tk.Frame(tbl_frame, bg=SURFACE2)
                col_f.grid(row=0, column=ci2, padx=6, pady=8, sticky="nw")
                tk.Label(col_f, text=hdr or f"(kolom {ci2+1})",
                         bg=SURFACE2, fg=ACCENT2,
                         font=(UI_FONT, 10, "bold")).pack(anchor="w")
                var = tk.StringVar(value=t("field_ignore"))
                # Slim voorstel op basis van kolomnaam
                h_low = hdr.lower()
                if any(k in h_low for k in ("take", "tak")):
                    var.set(t("field_take"))
                elif any(k in h_low for k in ("scene", "slate", "scèn", "scen")):
                    var.set(t("field_slate_scene"))
                elif any(k in h_low for k in ("opmerking", "note", "comment", "descr")):
                    var.set(t("field_note"))
                elif any(k in h_low for k in ("rating", "circle", "beoord", "✓", "v/x")):
                    var.set(t("field_rating"))
                elif any(k in h_low for k in ("camera", "roll", "tape", "kaart", "card")):
                    var.set(t("field_camera_roll"))
                col_vars.append(var)
                om = tk.OptionMenu(col_f, var, *FIELD_OPTIONS)
                om.config(bg=SURFACE2, fg=TEXT, activebackground=BORDER,
                          font=(UI_FONT, 9), width=12)
                om["menu"].config(bg=SURFACE2, fg=TEXT)
                om.pack(anchor="w", pady=2)
                # Preview eerste paar waarden
                for row2 in sample_rows[:3]:
                    val = row2[ci2] if ci2 < len(row2) else ""
                    tk.Label(col_f, text=val[:18] or "–",
                             bg=SURFACE2, fg=MUTED,
                             font=(UI_FONT, 9)).pack(anchor="w")

            # Naam voor deze layout
            name_row = tk.Frame(dlg, bg=BG)
            name_row.pack(fill="x", padx=24, pady=(0, 12))
            tk.Label(name_row, text=t("layout_name_label"),
                     bg=BG, fg=MUTED, font=(UI_FONT, 11)).pack(
                side="left", padx=(0, 10))
            name_var = tk.StringVar(value=fname.split(".")[0])
            tk.Entry(name_row, textvariable=name_var, bg=SURFACE2, fg=TEXT,
                     insertbackground=TEXT, relief="flat",
                     font=(UI_FONT, 11), width=28).pack(side="left")

            status_lbl = tk.Label(dlg, text="", bg=BG, fg=MUTED,
                                  font=(UI_FONT, 10))
            status_lbl.pack(pady=(0, 6))

            btn_row = tk.Frame(dlg, bg=BG)
            btn_row.pack(pady=(0, 20))

            def _confirm():
                mapping = {}
                FIELD_MAP = {
                    t("field_slate_scene"):  "slate",
                    t("field_take"):         "take",
                    t("field_note"):         "note",
                    t("field_rating"):       "rating",
                    t("field_camera_roll"):  "camera_roll",
                }
                for ci3, var in enumerate(col_vars):
                    field = FIELD_MAP.get(var.get())
                    if field:
                        mapping[field] = sample_headers[ci3]
                if "take" not in mapping:
                    status_lbl.config(fg=ERROR, text=t("layout_no_take_col"))
                    return
                layout = {
                    "fingerprint": _fingerprint_table(sample_headers),
                    "name":        name_var.get().strip() or fname,
                    "mapping":     mapping,
                }
                _save_layout(layout)
                clips = _parse_pdf_custom(pdf_path, layout, self.log)
                dlg.destroy()
                on_done(clips if clips else None)

            def _skip():
                dlg.destroy()
                on_done(None)

            _rounded_btn(btn_row, t("btn_detect_process"), _confirm,
                         bg=AVID_B, hv=AVID_B_H, fg="white",
                         font=(UI_FONT, 11, "bold"),
                         px=20, py=7, r=10, pbg=BG).pack(side="left", padx=(0, 10))
            _rounded_btn(btn_row, t("btn_skip"), _skip,
                         bg=SURFACE2, hv=BORDER, fg=MUTED,
                         font=(UI_FONT, 11),
                         px=16, py=7, r=10, pbg=BG).pack(side="left")

        # ── FAQ-venster ──────────────────────────────────────────────────────
        def _show_faq():
            FAQ = [
                (t("faq_q10"), t("faq_a10")),
                (t("faq_q1"), t("faq_a1")),
                (t("faq_q2"), t("faq_a2")),
                (t("faq_q3"), t("faq_a3")),
                (t("faq_q4"), t("faq_a4")),
                (t("faq_q5"), t("faq_a5")),
                (t("faq_q6"), t("faq_a6")),
                (t("faq_q7"), t("faq_a7")),
                (t("faq_q8"), t("faq_a8")),
                (t("faq_q9"), t("faq_a9")),
            ]

            win = tk.Toplevel(self.root)
            win.title(t("wintitle_faq"))
            win.configure(bg=BG)
            win.resizable(False, True)
            win.geometry("560x620")
            win.minsize(480, 300)
            # Zelfde menubalk tonen ipv het macOS-standaardmenu (File/Edit/Window…)
            try:
                if getattr(self, "_menubar", None):
                    win.config(menu=self._menubar)
            except Exception:
                pass

            # ── Scrollable via Text widget trick ──────────────────────────────
            outer = tk.Frame(win, bg=BG)
            outer.pack(fill="both", expand=True)

            vsb = tk.Scrollbar(outer, orient="vertical")
            vsb.pack(side="right", fill="y")

            cv = tk.Canvas(outer, bg=BG, bd=0, highlightthickness=0,
                           yscrollcommand=vsb.set)
            cv.pack(side="left", fill="both", expand=True)
            vsb.config(command=cv.yview)

            inner = tk.Frame(cv, bg=BG)
            _cw = cv.create_window((4, 4), window=inner, anchor="nw")

            def _frame_changed(e=None):
                cv.configure(scrollregion=cv.bbox("all"))
                cv.itemconfig(_cw, width=cv.winfo_width() - 8)
            inner.bind("<Configure>", _frame_changed)
            cv.bind("<Configure>", _frame_changed)

            def _wheel(e):
                cv.yview_scroll(int(-1 * (e.delta / 60)), "units")
            win.bind_all("<MouseWheel>", _wheel)
            win.bind("<Destroy>", lambda e: win.unbind_all("<MouseWheel>"))

            # ── Header ────────────────────────────────────────────────────────
            tk.Label(inner, text=t("faq_title"), bg=BG, fg=TEXT,
                     font=(UI_FONT, 16, "bold"),
                     anchor="w").pack(anchor="w", padx=22, pady=(20, 2))
            tk.Label(inner, text=t("faq_subtitle"),
                     bg=BG, fg=MUTED, font=(UI_FONT, 10),
                     anchor="w").pack(anchor="w", padx=22, pady=(0, 14))

            # ── Accordion items ───────────────────────────────────────────────
            _HOVER   = "#1E1740"   # subtiele hover-achtergrond
            _ANS_BG  = SURFACE     # iets afwijkende achtergrond voor het antwoord
            _ANS_FG  = "#C9C0EA"   # goed leesbaar lavendel-wit voor de antwoordtekst

            def _relayout():
                inner.update_idletasks()
                cv.configure(scrollregion=cv.bbox("all"))

            def _make_card(q, a):
                card = tk.Frame(inner, bg=SURFACE2,
                                highlightbackground=BORDER, highlightthickness=1)
                card.pack(fill="x", padx=16, pady=4)

                state = {"open": False}
                chev  = tk.StringVar(value="▸")

                # Vraag-rij: accentbalk + tekst + chevron
                row = tk.Frame(card, bg=SURFACE2, cursor="arrow")
                row.pack(fill="x")
                bar = tk.Frame(row, bg=SURFACE2, width=3)
                bar.pack(side="left", fill="y")
                qlbl = tk.Label(row, text=q, bg=SURFACE2, fg=TEXT,
                                font=(UI_FONT, 12, "bold"),
                                wraplength=400, justify="left", anchor="w")
                qlbl.pack(side="left", padx=(13, 10), pady=14, fill="x", expand=True)
                chlbl = tk.Label(row, textvariable=chev, bg=SURFACE2, fg=ACCENT2,
                                 font=(UI_FONT, 13))
                chlbl.pack(side="right", padx=16)

                # Antwoord (verborgen)
                ans = tk.Frame(card, bg=_ANS_BG)
                tk.Label(ans, text=a, bg=_ANS_BG, fg=_ANS_FG,
                         font=(UI_FONT, 12),
                         wraplength=430, justify="left",
                         anchor="nw").pack(fill="x", padx=18, pady=(8, 16))

                def _set_row_bg(c):
                    row.config(bg=c); qlbl.config(bg=c); chlbl.config(bg=c)
                    if not state["open"]:
                        bar.config(bg=c)

                def _toggle(e=None):
                    state["open"] = not state["open"]
                    if state["open"]:
                        chev.set("▾")
                        bar.config(bg=AVID_B)
                        card.config(highlightbackground=AVID_B)
                        ans.pack(fill="x")
                    else:
                        chev.set("▸")
                        bar.config(bg=SURFACE2)
                        card.config(highlightbackground=BORDER)
                        ans.pack_forget()
                    _relayout()
                    cv.after(20, _relayout)   # opnieuw nadat de layout gezet is

                def _enter(e=None):
                    _set_row_bg(_HOVER)
                    if not state["open"]:
                        card.config(highlightbackground=AVID_B_H)
                def _leave(e=None):
                    _set_row_bg(SURFACE2)
                    if not state["open"]:
                        card.config(highlightbackground=BORDER)

                for w in (row, bar, qlbl, chlbl):
                    w.bind("<Button-1>", _toggle)
                    w.bind("<Enter>", _enter)
                    w.bind("<Leave>", _leave)

            for q, a in FAQ:
                _make_card(q, a)

            tk.Frame(inner, bg=BG, height=16).pack()
            win.after(50, _frame_changed)

        # ── About-venster ────────────────────────────────────────────────────
        def _show_about():
            win = tk.Toplevel(self.root)
            win.title(t("wintitle_about"))
            win.resizable(False, False)
            win.configure(bg=BG)
            win.geometry("340x280")
            try:
                if getattr(self, "_menubar", None):
                    win.config(menu=self._menubar)
            except Exception:
                pass
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
                     font=(UI_FONT, 15, "bold")).pack()
            tk.Label(win, text=t("about_version", ver=VERSION), bg=BG, fg=MUTED,
                     font=(UI_FONT, 11)).pack(pady=(2, 0))
            tk.Label(win, text=t("about_author"), bg=BG, fg=MUTED,
                     font=(UI_FONT, 11)).pack(pady=(2, 4))
            _mail = tk.Label(win, text="support@studiomichielboesveldt.nl",
                             bg=BG, fg=AVID_B,
                             font=(UI_FONT, 10, "underline"),
                             cursor="pointinghand")
            _mail.pack(pady=(0, 14))
            _mail.bind("<Button-1>", lambda e: __import__('webbrowser').open(
                "mailto:support@studiomichielboesveldt.nl"))
            _rounded_btn(win, t("btn_ok"), win.destroy,
                         bg=AVID_B, hv=AVID_B_H, fg="white",
                         font=(UI_FONT, 12, "bold"),
                         px=28, py=6, r=10, pbg=BG).pack()
            win.bind("<Return>", lambda e: win.destroy())
            win.bind("<Escape>", lambda e: win.destroy())

        # ── Licentiedialoog ──────────────────────────────────────────────────
        def _show_license_dialog(message="", block=False):
            """Toon dialoog voor serial invoer. block=True → app sluit bij annuleren."""
            dlg = tk.Toplevel(self.root)
            dlg.title(t("wintitle_license"))
            dlg.resizable(False, False)
            dlg.configure(bg=BG)
            dlg.geometry("400x420")
            dlg.grab_set()
            dlg.lift()
            dlg.focus_force()

            tk.Label(dlg, text="Continuity Bridge", bg=BG, fg=TEXT,
                     font=(UI_FONT, 14, "bold")).pack(pady=(20, 4))

            if message:
                tk.Label(dlg, text=message, bg=BG, fg=ERROR,
                         font=(UI_FONT, 10)).pack(pady=(4, 0))

            tk.Label(dlg, text=t("lic_name_label"), bg=BG, fg=MUTED,
                     font=(UI_FONT, 10)).pack(pady=(10, 3))
            name_var = tk.StringVar()
            name_entry = tk.Entry(dlg, textvariable=name_var, bg=SURFACE2, fg=TEXT,
                                  insertbackground=TEXT, relief="flat",
                                  font=(UI_FONT, 12), width=26,
                                  justify="center")
            name_entry.pack(ipady=6)
            name_entry.focus_set()

            tk.Label(dlg, text=t("lic_serial_label"), bg=BG, fg=MUTED,
                     font=(UI_FONT, 10)).pack(pady=(10, 3))
            serial_var = tk.StringVar()
            entry = tk.Entry(dlg, textvariable=serial_var, bg=SURFACE2, fg=TEXT,
                             insertbackground=TEXT, relief="flat",
                             font=(UI_FONT, 11), width=26,
                             justify="center")
            entry.pack(ipady=6)

            status_lbl = tk.Label(dlg, text="", bg=BG, fg=MUTED,
                                  font=(UI_FONT, 10))
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
                    status_lbl.config(fg=ERROR, text=t("lic_name_mismatch"))
                    return
                # Server-side activatiecheck
                status_lbl.config(fg=MUTED, text=t("lic_verify_msg"))
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
                            status_lbl.config(fg=ERROR, text=t("lic_already_bound"))
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

            _act_cv = _rounded_btn(dlg, t("lic_btn_activate"), _activate,
                                    bg=AVID_B, hv=AVID_B_H, fg="white",
                                    font=(UI_FONT, 12, "bold"),
                                    px=24, py=7, r=10, pbg=BG)
            _act_cv.pack(pady=(8, 0))
            name_entry.bind("<Return>", lambda e: entry.focus_set())
            entry.bind("<Return>", lambda e: _activate())

            if block:
                _SHOP_URL = "https://payment-links.mollie.com/payment/NesoriUjVmqbLs84L5mrP"
                _shop_cv  = _rounded_btn(dlg, t("lic_btn_buy"),
                                         lambda: __import__('webbrowser').open(_SHOP_URL),
                                         bg=SUCCESS, hv="#3ab870", fg="#0A2A10",
                                         font=(UI_FONT, 11, "bold"),
                                         px=18, py=6, r=10, pbg=BG)
                _shop_cv.pack(pady=(12, 0))
                tk.Label(dlg, text=t("lic_buy_after"),
                         bg=BG, fg=MUTED, font=(UI_FONT, 9)).pack(pady=(6, 0))
                mail_lbl = tk.Label(dlg, text="support@studiomichielboesveldt.nl",
                                    bg=BG, fg=AVID_B,
                                    font=(UI_FONT, 9, "underline"),
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
                        win.title(t("wintitle_license_info"))
                        win.resizable(False, False)
                        win.configure(bg=BG)
                        win.geometry("340x230")
                        win.grab_set(); win.lift(); win.focus_force()
                        tk.Label(win, text=t("lic_active_label"), bg=BG, fg=SUCCESS,
                                 font=(UI_FONT, 13, "bold")).pack(pady=(20, 4))
                        tk.Label(win, text=name, bg=BG, fg=TEXT,
                                 font=(UI_FONT, 14, "bold")).pack()
                        tk.Label(win, text=msg, bg=BG, fg=MUTED,
                                 font=(UI_FONT, 11)).pack(pady=(4, 10))
                        tk.Label(win, text=serial, bg=BG, fg=MUTED,
                                 font=(MONO_FONT, 9), wraplength=300).pack(pady=(0, 8))
                        _sl = tk.Label(win, text="support@studiomichielboesveldt.nl",
                                       bg=BG, fg=AVID_B,
                                       font=(UI_FONT, 9, "underline"),
                                       cursor="pointinghand")
                        _sl.pack(pady=(0, 10))
                        _sl.bind("<Button-1>", lambda e: __import__('webbrowser').open(
                            "mailto:support@studiomichielboesveldt.nl"))
                        _rounded_btn(win, t("btn_ok"), win.destroy,
                                     bg=AVID_B, hv=AVID_B_H, fg="white",
                                     font=(UI_FONT, 12, "bold"),
                                     px=28, py=6, r=10, pbg=BG).pack()
                        win.bind("<Return>", lambda e: win.destroy())
                        win.bind("<Escape>", lambda e: win.destroy())
                    else:
                        if ok is False and serial and msg not in ("Geen licentie.",):
                            # revoked / expired → block
                            _license_delete()
                            self._license_expiry = None
                            _show_license_dialog(message=msg, block=True)
                        elif tk.messagebox.askyesno(t("wintitle_lic_question"), f"{msg}\n\n{t('lic_ask_new_serial')}"):
                            _show_license_dialog()
                self.root.after(0, _render)
            threading.Thread(target=_do_show, daemon=True).start()

        def _remove_license():
            if tk.messagebox.askyesno(t("wintitle_remove_lic"), t("lic_remove_confirm")):
                _license_delete()
                self._license_expiry = None
                _show_license_dialog(message=t("lic_removed_msg"), block=True)

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
            win.title(t("wintitle_sold"))
            win.configure(bg=BG)
            win.geometry("860x540")
            win.grab_set(); win.lift(); win.focus_force()

            # Token-balk bovenaan
            hdr = tk.Frame(win, bg=SURFACE, pady=8, padx=14)
            hdr.pack(fill="x")
            tk.Label(hdr, text=t("mgr_token_label"), bg=SURFACE, fg=MUTED,
                     font=(UI_FONT, 11)).pack(side="left")
            tok_var = tk.StringVar(value=_mgr_token_load())
            tok_entry = tk.Entry(hdr, textvariable=tok_var, show="•", width=44,
                                 bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                                 relief="flat", font=(MONO_FONT, 10), bd=4)
            tok_entry.pack(side="left", padx=(8, 6))
            _mgr_token_save_btn = tk.Button(hdr, text=t("mgr_btn_save_load"),
                                            bg=AVID_B, fg="white",
                                            font=(UI_FONT, 10, "bold"),
                                            relief="flat", bd=0, cursor="hand2",
                                            padx=10, pady=4)
            hdr.pack(fill="x")

            # Status-label
            status_lbl = tk.Label(win, text="", bg=BG, fg=MUTED,
                                   font=(UI_FONT, 10))
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
                font=(UI_FONT, 11))
            style.configure("Lic.Treeview.Heading",
                background=SURFACE2, foreground=MUTED,
                font=(UI_FONT, 10, "bold"))
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
            revoke_btn = tk.Button(btn_row, text=t("mgr_revoke_btn"),
                                   bg=ERROR, fg="white",
                                   font=(UI_FONT, 11, "bold"),
                                   relief="flat", bd=0, cursor="hand2",
                                   padx=12, pady=6, state="disabled")
            revoke_btn.pack(side="left")
            count_lbl = tk.Label(btn_row, text="", bg=BG, fg=MUTED,
                                  font=(UI_FONT, 10))
            count_lbl.pack(side="right")

            _licenses_cache = []   # mutable closure list

            def _load_data():
                token = tok_var.get().strip()
                if not token:
                    status_lbl.config(text=t("mgr_enter_token"), fg=ERROR)
                    return
                _mgr_token_save(token)
                status_lbl.config(text=t("mgr_loading"), fg=MUTED)
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
                                        status = t("mgr_status_revoked")
                                    elif expiry and today >= expiry:
                                        status = t("mgr_status_expired")
                                    else:
                                        status = t("mgr_status_valid")
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
                            text=t("mgr_fetch_err", err=str(ex)), fg=ERROR))
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
                if not tk.messagebox.askyesno(t("wintitle_revoke"),
                        t("mgr_revoke_confirm", naam=naam, serial=serial_str)):
                    return
                token = tok_var.get().strip()
                status_lbl.config(text=t("mgr_revoking"), fg=MUTED)
                serial_clean = serial_str.upper().replace(" ", "")

                def _revoke():
                    try:
                        _revoke_serial_on_github(token, serial_clean)
                        self.root.after(0, lambda: (
                            status_lbl.config(text=t("mgr_revoked_ok", serial=serial_clean[:16]), fg=SUCCESS),
                            _load_data()
                        ))
                    except Exception as ex:
                        self.root.after(0, lambda: status_lbl.config(
                            text=t("mgr_revoke_err", err=str(ex)), fg=ERROR))
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
            _appmenu.add_command(label=t('menu_about'), command=_show_about)
            _appmenu.add_separator()
            _appmenu.add_command(label=t('menu_prefs'), command=self._show_prefs,
                                 accelerator='Command+,')
            _appmenu.add_separator()
            _appmenu.add_command(label=t('menu_quit'),
                                 command=self.root.quit,
                                 accelerator='Command+Q')
            _menubar.add_cascade(label='Continuity Bridge', menu=_appmenu)

            # Help-menu
            _helpmenu = tk.Menu(_menubar, tearoff=False)
            _helpmenu.add_command(label=t('menu_license'), command=_show_license_info)
            _helpmenu.add_command(label=t('menu_remove_license'), command=_remove_license)
            _helpmenu.add_separator()
            _helpmenu.add_command(label=t('menu_faq'), command=_show_faq)
            _helpmenu.add_separator()
            _helpmenu.add_command(label=t('menu_check_updates'),
                                  command=lambda: _check_updates(silent=False))
            _menubar.add_cascade(label='Help', menu=_helpmenu)

            self.root.config(menu=_menubar)
            self._menubar = _menubar   # zodat Toplevels dezelfde menubalk kunnen tonen
            self.root.createcommand('tk::mac::ShowAbout', _show_about)
            self.root.createcommand('tk::mac::ShowPreferences', self._show_prefs)
            # macOS koppelt het systeem-Help-menu hieraan; open onze FAQ ipv "Help niet beschikbaar"
            self.root.createcommand('tk::mac::ShowHelp', _show_faq)
        except Exception:
            pass

        self.root.bind_all('<Command-comma>', lambda e: self._show_prefs())
        self.root.bind_all('<Command-q>', lambda e: self.root.quit())
        try:
            self.root.createcommand('tk::mac::Quit', self.root.quit)
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
        # Opgeslagen interfacegrootte toepassen (fonts direct schalen)
        if self._ui_scale_pct != 100:
            self.root.after(0, self._apply_appearance_live)
        if HAS_NATIVE_DND and not HAS_DND:
            self.root.after(500, self._setup_native_dnd)

    def _pick_column(self, var, parent_win=None):
        """Zoekbaar keuzevenster met alle bekende Avid-kolomnamen."""
        _prev_val = var.get()
        anchor = parent_win or self.root

        dlg = tk.Toplevel(anchor)
        dlg.title(t("wintitle_col_pick"))
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
        tk.Label(dlg, text=t("col_pick_search"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(anchor="w", padx=16, pady=(14, 4))
        search_var = tk.StringVar()
        ent = tk.Entry(dlg, textvariable=search_var, width=30,
                       bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                       relief="flat", font=(UI_FONT, 12),
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
                        font=(UI_FONT, 11), activestyle="none",
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
        tk.Label(own_frame, text=t("col_pick_own_label"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left")
        own_var = tk.StringVar()
        own_ent = tk.Entry(own_frame, textvariable=own_var, width=18,
                           bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                           relief="flat", font=(UI_FONT, 11),
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
        _rounded_btn(btn_row, t("btn_cancel"), _cancel,
                     bg=SURFACE2, hv=SURFACE, fg=TEXT,
                     font=(UI_FONT, 11), px=16, py=6, r=8, pbg=BG).pack(side="left", padx=(0, 8))
        _rounded_btn(btn_row, t("btn_pick"), lambda: _confirm(
                         _lb_map[lb.curselection()[0]] if lb.curselection() and _lb_map[lb.curselection()[0]] else None),
                     bg=AVID_B, hv="#2a6fbd", fg="white",
                     font=(UI_FONT, 11, "bold"), px=16, py=6, r=8, pbg=BG).pack(side="left")

        dlg.update_idletasks()
        cx = anchor.winfo_x() + anchor.winfo_width()  // 2
        cy = anchor.winfo_y() + anchor.winfo_height() // 2
        dlg.geometry(f"+{cx - dlg.winfo_width()//2}+{cy - dlg.winfo_height()//2}")
        dlg.wait_window()

    def _show_prefs(self):
        """Voorkeuren-venster (modaal)."""
        win = tk.Toplevel(self.root)
        win.title(t("wintitle_prefs"))
        win.resizable(False, False)
        win.configure(bg=BG)
        win.grab_set()
        try:
            if getattr(self, "_menubar", None):
                win.config(menu=self._menubar)
        except Exception:
            pass

        PAD = 20
        ROW = 32

        # ── Scrollbaar canvas zodat alles bereikbaar blijft (ook bij grote schaal) ─
        _outer = tk.Frame(win, bg=BG)
        _outer.pack(fill="both", expand=True)
        _vsb = tk.Scrollbar(_outer, orient="vertical")
        _vsb.pack(side="right", fill="y")
        _pcv = tk.Canvas(_outer, bg=BG, bd=0, highlightthickness=0,
                         yscrollcommand=_vsb.set)
        _pcv.pack(side="left", fill="both", expand=True)
        _vsb.config(command=_pcv.yview)
        _content = tk.Frame(_pcv, bg=BG)
        _pwin = _pcv.create_window((0, 0), window=_content, anchor="nw")

        def _pcv_conf(e=None):
            _pcv.configure(scrollregion=_pcv.bbox("all"))
            _pcv.itemconfig(_pwin, width=_pcv.winfo_width())
        _content.bind("<Configure>", _pcv_conf)
        _pcv.bind("<Configure>", _pcv_conf)
        def _pcv_wheel(e):
            _pcv.yview_scroll(int(-1 * (e.delta / 60)), "units")
        win.bind_all("<MouseWheel>", _pcv_wheel)
        win.bind("<Destroy>", lambda e: win.unbind_all("<MouseWheel>"))

        # ── Titel ──────────────────────────────────────────────────────────
        tk.Label(_content, text=t("prefs_title"), bg=BG, fg=TEXT,
                 font=(UI_FONT, 15, "bold")).pack(anchor="w", padx=PAD, pady=(PAD, 14))

        tk.Frame(_content, bg=BORDER, height=1).pack(fill="x", padx=PAD)

        # In/uitklapbare secties: klik op de kop om te vouwen
        _sec = [None]   # huidige sectie-inhoud waar rijen in komen
        def _section(label, collapsed=False):
            hdr = tk.Frame(_content, bg=BG, cursor="arrow")
            hdr.pack(fill="x", padx=PAD, pady=(12, 2))
            chev = tk.StringVar(value="▸" if collapsed else "▾")
            tk.Label(hdr, textvariable=chev, bg=BG, fg=AVID_B,
                     font=(UI_FONT, 9, "bold")).pack(side="left", padx=(0, 5))
            tk.Label(hdr, text=label, bg=BG, fg=AVID_B,
                     font=(UI_FONT, 9, "bold")).pack(side="left")
            tk.Frame(hdr, bg=BORDER, height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0), pady=(1, 0))
            cont = tk.Frame(_content, bg=BG)
            cont.pack(fill="x", padx=PAD, pady=(0, 4), after=hdr)
            _sec[0] = cont
            state = {"open": not collapsed}
            if collapsed:
                cont.pack_forget()
            def _toggle(e=None):
                state["open"] = not state["open"]
                chev.set("▾" if state["open"] else "▸")
                if state["open"]:
                    # Altijd terug direct ná de eigen kop (behoud volgorde)
                    cont.pack(fill="x", padx=PAD, pady=(0, 4), after=hdr)
                else:
                    cont.pack_forget()
                self.root.after(1, _pcv_conf)
            for wdg in (hdr, *hdr.winfo_children()):
                wdg.bind("<Button-1>", _toggle)
            return cont

        def _row(label):
            f = tk.Frame(_sec[0], bg=BG, height=ROW)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=label, bg=BG, fg=MUTED,
                     font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
            return f

        # Stijl voor alle comboboxen in dit venster
        style = ttk.Style()
        CUSTOM = t("col_pick_placeholder")

        def _cb(parent, var, values):
            # Bewerkbaar: kies uit de lijst óf typ zelf een exacte kolomnaam
            # (matcht hoofdletterongevoelig op een bestaande Avid-kolom).
            all_values = list(values) + [CUSTOM]
            cb = ttk.Combobox(parent, textvariable=var, values=all_values,
                              state="normal", width=16,
                              style="CB.TCombobox", font=(UI_FONT, 11))
            cb.pack(side="left")
            def _on_select(e):
                if var.get() == CUSTOM:
                    self._pick_column(var, win)
            cb.bind("<<ComboboxSelected>>", _on_select)
            return cb

        _section(t("prefs_section_per_take"))

        # Notes: checkbox + "→" + kolom-dropdown
        r2 = _row(t("prefs_notes"))
        tk.Checkbutton(r2, variable=self.write_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r2, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb(r2, self.notes_col, self.NOTES_COLS)

        # Scene: checkbox + "→" + kolom-dropdown (vink uit = originele Scene niet overschrijven)
        r_scene = _row(t("prefs_scene"))
        tk.Checkbutton(r_scene, variable=self.write_scene,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r_scene, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb(r_scene, self.scene_col, ["Auto", "Scene"])

        # Rating: checkbox + "→" + kolom-dropdown + format (sterren/***/cijfer)
        r1 = _row(t("prefs_rating"))
        tk.Checkbutton(r1, variable=self.write_rating,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r1, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb(r1, self.rating_col, self.RATING_COLS)
        tk.Label(r1, text=t("prefs_stars_as"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(10, 4))
        _STAR_DISPLAY = [t("prefs_stars_stars"), t("prefs_stars_number"), t("prefs_stars_letter")]
        _STAR_TO_CODE = {t("prefs_stars_stars"): "sterren", t("prefs_stars_number"): "cijfer", t("prefs_stars_letter"): "letters"}
        _CODE_TO_STAR = {"sterren": t("prefs_stars_stars"), "cijfer": t("prefs_stars_number"), "letters": t("prefs_stars_letter")}
        _star_display = tk.StringVar(value=_CODE_TO_STAR.get(self.star_format.get(), _STAR_DISPLAY[0]))
        _star_cb = ttk.Combobox(r1, textvariable=_star_display,
                     values=_STAR_DISPLAY, state="readonly", width=13,
                     style="CB.TCombobox",
                     font=(UI_FONT, 11))
        _star_cb.pack(side="left")
        def _on_star_fmt(e):
            self.star_format.set(_STAR_TO_CODE.get(_star_display.get(), "sterren"))
        _star_cb.bind("<<ComboboxSelected>>", _on_star_fmt)

        # PU: checkbox + "→" + kolom-dropdown + voor/achter
        PU_COLS = ["Auto", "Comment", "Comments", "Notes", "Take_Notes"]
        r5 = _row(t("prefs_write_pu"))
        tk.Checkbutton(r5, variable=self.write_pu_in_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r5, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb(r5, self.pu_col, PU_COLS)
        tk.Label(r5, text=t("prefs_position"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(8, 4))
        _POS_DISPLAY = [t("prefs_pos_before"), t("prefs_pos_after")]
        _POS_TO_CODE = {t("prefs_pos_before"): "voor", t("prefs_pos_after"): "achter"}
        _CODE_TO_POS = {"voor": t("prefs_pos_before"), "achter": t("prefs_pos_after")}
        _pu_pos_display = tk.StringVar(value=_CODE_TO_POS.get(self.pu_position.get(), _POS_DISPLAY[0]))
        _pu_pos_cb = ttk.Combobox(r5, textvariable=_pu_pos_display,
                     values=_POS_DISPLAY, state="readonly", width=7,
                     style="CB.TCombobox",
                     font=(UI_FONT, 11))
        _pu_pos_cb.pack(side="left")
        def _on_pu_pos(e):
            self.pu_position.set(_POS_TO_CODE.get(_pu_pos_display.get(), "voor"))
        _pu_pos_cb.bind("<<ComboboxSelected>>", _on_pu_pos)

        # PU eigen kolom: checkbox + kolomnaam entry
        r5b = _row(t("prefs_pu_own_col"))
        tk.Checkbutton(r5b, variable=self.pu_eigen_kolom,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r5b, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        tk.Label(r5b, text=t("prefs_pu_col_name") + ":", bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(0, 4))
        _pu_kn_entry = tk.Entry(r5b, textvariable=self.pu_eigen_kolom_naam,
                                width=10, bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                                relief="flat", font=(UI_FONT, 11))
        _pu_kn_entry.pack(side="left")

        # AFG: checkbox + "→" + kolom-dropdown + voor/achter
        AFG_COLS = ["Auto", "Comment", "Comments", "Notes", "Take_Notes"]
        r6 = _row(t("prefs_write_afg"))
        tk.Checkbutton(r6, variable=self.write_afg_in_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r6, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb(r6, self.afg_col, AFG_COLS)
        tk.Label(r6, text=t("prefs_position"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(8, 4))
        _afg_pos_display = tk.StringVar(value=_CODE_TO_POS.get(self.afg_position.get(), _POS_DISPLAY[0]))
        _afg_pos_cb = ttk.Combobox(r6, textvariable=_afg_pos_display,
                     values=_POS_DISPLAY, state="readonly", width=7,
                     style="CB.TCombobox",
                     font=(UI_FONT, 11))
        _afg_pos_cb.pack(side="left")
        def _on_afg_pos(e):
            self.afg_position.set(_POS_TO_CODE.get(_afg_pos_display.get(), "voor"))
        _afg_pos_cb.bind("<<ComboboxSelected>>", _on_afg_pos)

        def _row2(label):
            f = tk.Frame(_sec[0], bg=BG, height=ROW)
            f.pack(fill="x", pady=3)
            tk.Label(f, text=label, bg=BG, fg=MUTED,
                     font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
            return f

        SOUND_COLS  = ["Sound_Notes", "Sound", "Audio_Notes"]
        CAMERA_COLS = ["Camera_Notes", "Continuity_Notes", "Script_Notes"]
        GEN_COLS    = ["Camera_Notes", "Opmerkingen", "Continuity_Notes", "Script_Notes"]

        def _cb2(parent, var, values):
            CUSTOM = t("col_pick_placeholder")
            cb = ttk.Combobox(parent, textvariable=var, values=list(values) + [CUSTOM],
                              state="normal", width=16,
                              style="CB.TCombobox", font=(UI_FONT, 11))
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>",
                    lambda e: self._pick_column(var, win) if var.get() == CUSTOM else None)
            return cb

        _section(t("prefs_section_general"))

        r7 = _row2(t("prefs_sound_notes"))
        tk.Checkbutton(r7, variable=self.write_sound_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r7, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb2(r7, self.sound_notes_col, SOUND_COLS)

        r8 = _row2(t("prefs_camera_notes"))
        tk.Checkbutton(r8, variable=self.write_camera_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r8, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb2(r8, self.camera_notes_col, CAMERA_COLS)

        r9 = _row2(t("prefs_opmerkingen"))
        tk.Checkbutton(r9, variable=self.write_general_notes,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r9, text="→", bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 6))
        _cb2(r9, self.general_notes_col, GEN_COLS)

        # ── UITVOER ───────────────────────────────────────────────────────────
        _out = _section(t("prefs_section_output"))

        # Uitvoermap
        r4 = tk.Frame(_out, bg=BG, height=ROW)
        r4.pack(fill="x", pady=4)
        tk.Label(r4, text=t("prefs_output_dir"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        out_entry = tk.Entry(r4, textvariable=self.output_dir, width=22,
                             bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                             relief="flat", font=(UI_FONT, 11),
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=AVID_B)
        out_entry.pack(side="left", ipady=3)

        def _pick_dir():
            d = filedialog.askdirectory(title=t("dlg_pick_dir"),
                                        initialdir=self.output_dir.get() or Path.home())
            if d:
                self.output_dir.set(d)
        _rounded_btn(r4, t("btn_choose_dir"), _pick_dir,
                     bg=SURFACE2, hv=BORDER, fg=TEXT,
                     font=(UI_FONT, 11), px=10, py=3, r=6,
                     pbg=BG).pack(side="left", padx=(4, 0))
        tk.Label(r4, text=t("prefs_output_dir_hint"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(8, 0))

        # Bestandsnaam
        r4b = tk.Frame(_out, bg=BG, height=ROW)
        r4b.pack(fill="x", pady=4)
        tk.Label(r4b, text=t("prefs_filename"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        tk.Label(r4b, text=t("prefs_filename_orig"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left")
        tk.Entry(r4b, textvariable=self.output_suffix, width=20,
                 bg=SURFACE2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=(UI_FONT, 11),
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=AVID_B).pack(side="left", ipady=3, padx=(4, 0))
        tk.Label(r4b, text=".ALE / .avb", bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(4, 0))

        # Map met resultaat openen na verwerken
        r_open = tk.Frame(_out, bg=BG)
        r_open.pack(fill="x", pady=3)
        tk.Checkbutton(r_open, variable=self.open_folder_after,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r_open, text=t("prefs_open_folder"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 0))

        # Umlauten transliteren (vangnet voor oude Avid)
        r_translit = tk.Frame(_out, bg=BG)
        r_translit.pack(fill="x", pady=3)
        tk.Checkbutton(r_translit, variable=self.translit_umlauts,
                       bg=BG, fg=TEXT, selectcolor=SURFACE2,
                       activebackground=BG, activeforeground=TEXT,
                       font=(UI_FONT, 11), relief="flat", bd=0).pack(side="left")
        tk.Label(r_translit, text=t("prefs_translit"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11)).pack(side="left", padx=(4, 0))

        # ALE-codering: Auto (zoals invoer) / UTF-8 / Mac Roman.
        # Nodig omdat een verse dag-export vaak puur ASCII is: dan valt de
        # invoer-encoding niet te detecteren, terwijl de PDF-notes wél
        # umlauten kunnen bevatten. Oudere Avid = Mac Roman.
        r_enc = tk.Frame(_out, bg=BG)
        r_enc.pack(fill="x", pady=3)
        tk.Label(r_enc, text=t("prefs_ale_encoding"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        _ENC_OPTS  = [t("enc_auto"), t("enc_utf8"), t("enc_macroman")]
        _ENC_CODES = {t("enc_auto"): "auto", t("enc_utf8"): "utf-8",
                      t("enc_macroman"): "mac_roman"}
        _ENC_LABELS = {v: k for k, v in _ENC_CODES.items()}
        _enc_disp = tk.StringVar(value=_ENC_LABELS.get(self.ale_encoding.get(),
                                                       t("enc_auto")))
        enc_cb = ttk.Combobox(r_enc, textvariable=_enc_disp,
                              values=_ENC_OPTS, state="readonly", width=22,
                              style="CB.TCombobox", font=(UI_FONT, 11))
        enc_cb.pack(side="left")
        def _on_enc(e=None):
            self.ale_encoding.set(_ENC_CODES.get(_enc_disp.get(), "auto"))
        enc_cb.bind("<<ComboboxSelected>>", _on_enc)

        # Wissen na verwerken: modus + vertraging
        r_clear = tk.Frame(_out, bg=BG)
        r_clear.pack(fill="x", pady=3)
        tk.Label(r_clear, text=t("prefs_clear_label"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        _CLEAR_OPTS  = [t("clear_mode_uit"), t("clear_mode_vragen"), t("clear_mode_auto")]
        _CLEAR_CODES = {t("clear_mode_uit"): "uit", t("clear_mode_vragen"): "vragen",
                        t("clear_mode_auto"): "automatisch"}
        _CLEAR_LABELS = {v: k for k, v in _CLEAR_CODES.items()}
        _clear_disp = tk.StringVar(value=_CLEAR_LABELS.get(self.clear_mode.get(),
                                                           t("clear_mode_vragen")))
        clear_cb = ttk.Combobox(r_clear, textvariable=_clear_disp,
                                values=_CLEAR_OPTS, state="readonly", width=12,
                                style="CB.TCombobox", font=(UI_FONT, 11))
        clear_cb.pack(side="left")
        _delay_lbl = tk.Label(r_clear, text=t("prefs_clear_delay"), bg=BG, fg=MUTED,
                              font=(UI_FONT, 10))
        _delay_lbl.pack(side="left", padx=(10, 4))
        _DELAYS = [str(s) for s in range(0, 61, 5)]
        _delay_disp = tk.StringVar(value=str(self.clear_delay.get()))
        delay_cb = ttk.Combobox(r_clear, textvariable=_delay_disp,
                                values=_DELAYS, state="readonly", width=4,
                                style="CB.TCombobox", font=(UI_FONT, 11))
        delay_cb.pack(side="left")
        tk.Label(r_clear, text=t("clear_delay_unit"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 10)).pack(side="left", padx=(4, 0))
        def _sync_delay_state():
            on = self.clear_mode.get() in ("vragen", "automatisch")
            delay_cb.config(state="readonly" if on else "disabled")
            _delay_lbl.config(fg=MUTED if on else BORDER)
        def _on_clear_mode(e=None):
            self.clear_mode.set(_CLEAR_CODES.get(_clear_disp.get(), "vragen"))
            _sync_delay_state()
        def _on_delay(e=None):
            try: self.clear_delay.set(int(_delay_disp.get()))
            except ValueError: pass
        clear_cb.bind("<<ComboboxSelected>>", _on_clear_mode)
        delay_cb.bind("<<ComboboxSelected>>", _on_delay)
        _sync_delay_state()

        # ── UITERLIJK ─────────────────────────────────────────────────────────
        _app = _section(t("prefs_section_appearance"), collapsed=True)

        # Interfacegrootte: custom canvas-slider 10-200% + reset
        r_scale = tk.Frame(_app, bg=BG)
        r_scale.pack(fill="x", pady=3)
        tk.Label(r_scale, text=t("prefs_ui_scale"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        _SL_W, _SL_H, _LO, _HI = 180, 24, 10, 200
        _sl_cv = tk.Canvas(r_scale, width=_SL_W, height=_SL_H, bg=BG,
                           bd=0, highlightthickness=0, cursor="arrow")
        _sl_cv.pack(side="left")
        _sl_lbl = tk.Label(r_scale, text=f"{self.ui_scale.get()}%", bg=BG, fg=TEXT,
                           width=5, anchor="w", font=(UI_FONT, 11))
        _sl_lbl.pack(side="left", padx=(8, 0))
        _pad = 10
        def _val_to_x(v):
            return _pad + (v - _LO) / (_HI - _LO) * (_SL_W - 2 * _pad)
        def _x_to_val(x):
            frac = (x - _pad) / (_SL_W - 2 * _pad)
            v = _LO + max(0.0, min(1.0, frac)) * (_HI - _LO)
            return int(round(v / 5) * 5)
        def _draw_slider():
            _sl_cv.delete("all")
            cy = _SL_H // 2
            _sl_cv.create_line(_pad, cy, _SL_W - _pad, cy,
                               fill=SURFACE2, width=4, capstyle="round")
            hx = _val_to_x(self.ui_scale.get())
            _sl_cv.create_line(_pad, cy, hx, cy,
                               fill=AVID_B, width=4, capstyle="round")
            _sl_cv.create_oval(hx - 8, cy - 8, hx + 8, cy + 8,
                               fill="white", outline=AVID_B, width=2)
        def _set_from_x(x):
            v = _x_to_val(x)
            if v != self.ui_scale.get():
                self.ui_scale.set(v)
                _sl_lbl.config(text=f"{v}%")
            _draw_slider()
        def _on_drag(e):
            _set_from_x(e.x)
        def _on_release(e):
            _set_from_x(e.x)
            self._apply_appearance_live()
            _draw_slider()
        _sl_cv.bind("<Button-1>", _on_drag)
        _sl_cv.bind("<B1-Motion>", _on_drag)
        _sl_cv.bind("<ButtonRelease-1>", _on_release)
        _draw_slider()
        # Reset-knop (rondje-pijltje) → terug naar 100%
        _reset_lbl = tk.Label(r_scale, text="↺", bg=BG, fg=MUTED,
                              font=(UI_FONT, 15), cursor="arrow")
        _reset_lbl.pack(side="left", padx=(4, 0))
        def _reset_scale(e=None):
            self.ui_scale.set(100)
            _sl_lbl.config(text="100%")
            self._apply_appearance_live()
            _draw_slider()
        _reset_lbl.bind("<Button-1>", _reset_scale)
        _reset_lbl.bind("<Enter>", lambda e: _reset_lbl.config(fg=AVID_B))
        _reset_lbl.bind("<Leave>", lambda e: _reset_lbl.config(fg=MUTED))

        # Lettertype — elke keuze in z'n eigen font, met "Aa"-preview
        r_font = tk.Frame(_app, bg=BG)
        r_font.pack(fill="x", pady=3)
        tk.Label(r_font, text=t("prefs_ui_font"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left", anchor="n")
        _font_wrap = tk.Frame(r_font, bg=BG)
        _font_wrap.pack(side="left")
        _FONT_OPTS = [
            ("helvetica", t("font_helvetica"), "Helvetica Neue"),
            ("systeem",   t("font_systeem"),   ".AppleSystemUIFont"),
            ("leesbaar",  t("font_leesbaar"),  "Verdana"),
        ]
        _font_cells = {}
        def _refresh_fonts():
            for code, cell in _font_cells.items():
                sel = (self.ui_font.get() == code)
                cell.config(highlightbackground=AVID_B if sel else BORDER,
                            highlightthickness=2 if sel else 1)
        for code, label, fam in _FONT_OPTS:
            cell = tk.Frame(_font_wrap, bg=SURFACE2, highlightthickness=1,
                            highlightbackground=BORDER, cursor="arrow")
            cell.pack(side="left", padx=(0, 6))
            tk.Label(cell, text="Aa", bg=SURFACE2, fg=TEXT,
                     font=(fam, 18, "bold")).pack(padx=10, pady=(6, 0))
            _is_read = (code == "leesbaar")
            _lbl_font = (UI_FONT, 10, "bold") if _is_read else (UI_FONT, 9)
            tk.Label(cell, text=label, bg=SURFACE2,
                     fg=TEXT if _is_read else MUTED,
                     font=_lbl_font).pack(padx=10, pady=(0, 6))
            def _pick_font(e, c=code):
                self.ui_font.set(c)
                self._apply_appearance_live()
                _refresh_fonts()
            for wdg in (cell, *cell.winfo_children()):
                wdg.bind("<Button-1>", _pick_font)
            _font_cells[code] = cell
        _refresh_fonts()

        # Accentkleur: kleur-swatches
        r_accent = tk.Frame(_app, bg=BG)
        r_accent.pack(fill="x", pady=3)
        tk.Label(r_accent, text=t("prefs_accent"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        _sw_wrap = tk.Frame(r_accent, bg=BG)
        _sw_wrap.pack(side="left")
        _sw = {}
        def _refresh_sw():
            for code, cv in _sw.items():
                cv.delete("ring")
                if self.accent.get() == code:
                    cv.create_oval(2, 2, 22, 22, outline=TEXT, width=2, tags="ring")
        for code, (base, _h, _a) in ACCENT_THEMES.items():
            cv = tk.Canvas(_sw_wrap, width=26, height=26, bg=BG, bd=0,
                           highlightthickness=0, cursor="arrow")
            cv.pack(side="left", padx=(0, 6))
            cv.create_oval(5, 5, 21, 21, fill=base, outline="")
            def _pick(e, c=code):
                self.accent.set(c)
                self._apply_appearance_live()
                _refresh_sw()
            cv.bind("<Button-1>", _pick)
            _sw[code] = cv
        _refresh_sw()

        # ── TAAL ──────────────────────────────────────────────────────────────
        _langsec = _section(t("prefs_section_language"), collapsed=True)
        r_lang = tk.Frame(_langsec, bg=BG, height=32)
        r_lang.pack(fill="x", pady=3)
        tk.Label(r_lang, text=t("prefs_lang_label"), bg=BG, fg=MUTED,
                 font=(UI_FONT, 11), width=18, anchor="w").pack(side="left")
        _LANG_OPTIONS = ["\U0001F1F3\U0001F1F1 Nederlands", "\U0001F1EC\U0001F1E7 English", "\U0001F1E9\U0001F1EA Deutsch"]
        _LANG_CODES   = {_LANG_OPTIONS[0]: "nl", _LANG_OPTIONS[1]: "en", _LANG_OPTIONS[2]: "de"}
        _LANG_LABELS  = {v: k for k, v in _LANG_CODES.items()}
        _lang_display = tk.StringVar(value=_LANG_LABELS.get(self.language.get(), _LANG_OPTIONS[0]))
        lang_cb = ttk.Combobox(r_lang, textvariable=_lang_display,
                               values=_LANG_OPTIONS, state="readonly", width=16,
                               style="CB.TCombobox", font=(UI_FONT, 11))
        lang_cb.pack(side="left")
        tk.Label(r_lang, text=t("prefs_lang_restart_hint"),
                 bg=BG, fg=MUTED, font=(UI_FONT, 9)).pack(side="left", padx=(10, 0))
        def _on_lang_change(e):
            self.language.set(_LANG_CODES.get(_lang_display.get(), "nl"))
            self._save_prefs_all()
        lang_cb.bind("<<ComboboxSelected>>", _on_lang_change)


        # Sluit-knop
        btn = _rounded_btn(_content, t("btn_close"), win.destroy,
                           bg=AVID_B, hv="#2a6fbd", fg="white",
                           font=(UI_FONT, 12, "bold"),
                           px=24, py=8, r=10, pbg=BG)
        btn.pack(anchor="e", padx=PAD, pady=PAD)

        win.update_idletasks()
        _pcv_conf()
        # Expliciete grootte: content-breedte, hoogte gemaximeerd op ~85% scherm
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w = _content.winfo_reqwidth() + 16    # ruimte voor scrollbalk
        h = min(_content.winfo_reqheight(), int(sh * 0.85))
        x = max(20, (sw - w) // 2)
        y = max(20, (sh - h) // 3)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.resizable(False, True)   # verticaal schaalbaar
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
                    elif ext in (".ale", ".txt", ".avb"):
                        if filepath not in app_ref.ale_paths:
                            app_ref.ale_paths.append(filepath)
                            label = "AVB:  " if ext == ".avb" else "ALE:  "
                            app_ref._log_direct(f"{label}{p.name}", "info")
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

        # ── Pure-ctypes attach — geen PyObjC nodig (werkt op Silicon én Intel) ──
        _dnd_setup_done = [False]   # list zodat closure het kan muteren

        def attach():
            try:
                libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')

                libobjc.objc_getClass.restype         = ctypes.c_void_p
                libobjc.objc_getClass.argtypes        = [ctypes.c_char_p]
                libobjc.sel_registerName.restype      = ctypes.c_void_p
                libobjc.sel_registerName.argtypes     = [ctypes.c_char_p]
                libobjc.class_replaceMethod.restype   = ctypes.c_void_p
                libobjc.class_replaceMethod.argtypes  = [
                    ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.c_char_p,
                ]

                # Adres van objc_msgSend voor getypeerde wrappers
                _sa = ctypes.cast(libobjc.objc_msgSend, ctypes.c_void_p).value

                # Getypeerde msgSend-wrappers ──────────────────────────────
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

                def _v_p(obj, sel, arg):
                    """(obj, sel, id) → void"""
                    ctypes.CFUNCTYPE(
                        None, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_void_p
                    )(_sa)(obj, sel, arg)

                def _p_cs(cls, sel, s):
                    """class + stringWithUTF8String: → NSString"""
                    return ctypes.CFUNCTYPE(
                        ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_char_p
                    )(_sa)(cls, sel, s)

                # Veelgebruikte selectors ──────────────────────────────────
                SEL_count   = libobjc.sel_registerName(b'count')
                SEL_obj_at  = libobjc.sel_registerName(b'objectAtIndex:')
                SEL_utf8    = libobjc.sel_registerName(b'UTF8String')

                # ── Zoek het NSWindow van Continuity Bridge via NSApp ─────
                NSApp_cls       = libobjc.objc_getClass(b'NSApplication')
                NSStr_cls       = libobjc.objc_getClass(b'NSString')
                NSArr_cls       = libobjc.objc_getClass(b'NSArray')
                SEL_shared      = libobjc.sel_registerName(b'sharedApplication')
                SEL_windows     = libobjc.sel_registerName(b'windows')
                SEL_title       = libobjc.sel_registerName(b'title')
                SEL_content_v   = libobjc.sel_registerName(b'contentView')
                SEL_reg_types   = libobjc.sel_registerName(b'registerForDraggedTypes:')
                SEL_swu         = libobjc.sel_registerName(b'stringWithUTF8String:')
                SEL_arr_obj     = libobjc.sel_registerName(b'arrayWithObject:')

                if not NSApp_cls:
                    app_ref.root.after(300, attach)
                    return

                nsapp = _p(NSApp_cls, SEL_shared)
                if not nsapp:
                    app_ref.root.after(300, attach)
                    return

                windows  = _p(nsapp, SEL_windows)
                if not windows:
                    app_ref.root.after(300, attach)
                    return

                n_wins  = _u(windows, SEL_count)
                our_win = None
                for i in range(n_wins):
                    win = _p_u(windows, SEL_obj_at, i)
                    if not win:
                        continue
                    t_ns = _p(win, SEL_title)
                    if not t_ns:
                        continue
                    t_cs = _cs(t_ns, SEL_utf8)
                    if t_cs and t_cs == b'Continuity Bridge':
                        our_win = win
                        break

                if our_win is None:
                    app_ref.root.after(300, attach)
                    return

                cv = _p(our_win, SEL_content_v)
                if not cv:
                    app_ref.root.after(300, attach)
                    return

                # NSFilenamesPboardType als NSString ──────────────────────
                _nsfpt = _p_cs(NSStr_cls, SEL_swu, b'NSFilenamesPboardType')

                # registerForDraggedTypes: met NSArray van één element ─────
                def _register_drag_types():
                    arr = _p_p(NSArr_cls, SEL_arr_obj, _nsfpt)
                    if arr:
                        _v_p(cv, SEL_reg_types, arr)

                if _dnd_setup_done[0]:
                    # Methoden al gepatcht, alleen opnieuw registreren
                    _register_drag_types()
                    return

                # ── TKContentView-klasse patchen ──────────────────────────
                cls_ptr = libobjc.objc_getClass(b'TKContentView')
                if not cls_ptr:
                    return   # Tkinter-klasse niet gevonden

                # Selectors ───────────────────────────────────────────────
                SEL_pb      = libobjc.sel_registerName(b'draggingPasteboard')
                SEL_types   = libobjc.sel_registerName(b'types')
                SEL_plist   = libobjc.sel_registerName(b'propertyListForType:')
                SEL_entered = libobjc.sel_registerName(b'draggingEntered:')
                SEL_updated = libobjc.sel_registerName(b'draggingUpdated:')
                SEL_prepare = libobjc.sel_registerName(b'prepareForDragOperation:')
                SEL_perform = libobjc.sel_registerName(b'performDragOperation:')
                SEL_exited  = libobjc.sel_registerName(b'draggingExited:')

                # Helpers ─────────────────────────────────────────────────
                def _has_file_types(sender_p):
                    try:
                        pb = _p(sender_p, SEL_pb)
                        if not pb: return False
                        tys = _p(pb, SEL_types)
                        if not tys: return False
                        n = _u(tys, SEL_count)
                        for i in range(n):
                            ty = _p_u(tys, SEL_obj_at, i)
                            if ty and _cs(ty, SEL_utf8) == b'NSFilenamesPboardType':
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
                            item = _p_u(arr, SEL_obj_at, i)
                            if item:
                                s = _cs(item, SEL_utf8)
                                if s:
                                    out.append(s.decode('utf-8', errors='replace'))
                        return out
                    except Exception:
                        return []

                # IMP-types ───────────────────────────────────────────────
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

                # Ctypes callbacks — moeten in leven blijven (opgeslagen op app_ref)
                _imps = (
                    DragOpIMP(_imp_entered),
                    DragOpIMP(_imp_updated),
                    BoolIMP(_imp_prepare),
                    BoolIMP(_imp_perform),
                    VoidIMP(_imp_exited),
                )

                libobjc.class_replaceMethod(cls_ptr, SEL_entered, _imps[0], b'Q@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_updated, _imps[1], b'Q@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_prepare, _imps[2], b'B@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_perform, _imps[3], b'B@:@')
                libobjc.class_replaceMethod(cls_ptr, SEL_exited,  _imps[4], b'v@:@')

                app_ref._dnd_imps   = _imps   # voorkomt garbage collection
                _dnd_setup_done[0]  = True

                _register_drag_types()

            except Exception as _e:
                # Stille fout — DnD werkt niet, uploadknop blijft beschikbaar
                pass

        attach()

    def _ui(self):
        # ── Header (gradient canvas) ─────────────────────────────────────────
        _HDR_H  = 56

        hdr_cv = tk.Canvas(self.root, height=_HDR_H, bd=0, highlightthickness=0)
        hdr_cv.pack(fill="x")

        def _hex_rgb(h):
            h = h.lstrip('#')
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

        def _draw_hdr(event=None):
            w = hdr_cv.winfo_width()
            if w < 2:
                hdr_cv.after(20, _draw_hdr); return
            # Gradient afgeleid van de huidige accentkleur (AVID_B → donkerder)
            gl = _hex_rgb(ACCENT2 if ACCENT2 else AVID_B)
            gr = _hex_rgb(AVID_B_H)
            hdr_cv.delete("all")
            step = max(1, w // 300)
            for x in range(0, w + step, step):
                tt = min(x / (w - 1), 1.0)
                r = int(gl[0] + (gr[0] - gl[0]) * tt)
                g = int(gl[1] + (gr[1] - gl[1]) * tt)
                b = int(gl[2] + (gr[2] - gl[2]) * tt)
                hdr_cv.create_rectangle(x, 0, x + step, _HDR_H,
                                        fill=f"#{r:02x}{g:02x}{b:02x}", outline="")
            hdr_cv.create_text(22, _HDR_H // 2,
                               text="✦  Continuity Bridge", anchor="w",
                               fill="white", font=(UI_FONT, 15, "bold"))
            hdr_cv.create_text(w - 18, _HDR_H // 2,
                               text=f"v{VERSION}", anchor="e",
                               fill="white", font=(UI_FONT, 10))

        hdr_cv.bind("<Configure>", _draw_hdr)
        self._redraw_header = _draw_hdr

        # ── Body ─────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG, pady=22, padx=22)
        body.pack(fill="x")

        # Sectielabels met genummerd badge
        self._badges = []   # (canvas, nummer) — voor live herkleuren bij accentwissel
        def _section_label(parent, number, text):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", pady=(0, 7))
            # Badge: klein accent-vierkantje met nummer
            badge = tk.Canvas(row, width=20, height=20, bg=BG,
                              bd=0, highlightthickness=0)
            badge.pack(side="left", padx=(0, 8))
            def _draw_badge():
                badge.delete("all")
                badge.create_rectangle(0, 0, 20, 20, fill=AVID_B, outline="")
                badge.create_text(10, 10, text=str(number), fill="white",
                                  font=(UI_FONT, 11, "bold"))
            _draw_badge()
            self._badges.append(_draw_badge)
            tk.Label(row, text=text.upper(), bg=BG, fg=MUTED,
                     font=(UI_FONT, 11, "bold"), anchor="w").pack(side="left")

        _section_label(body, 1, t("section_ale"))
        self._multi_file_widget(body, self.ale_paths, "ALE").pack(fill="x", pady=(0, 14))

        _section_label(body, 2, t("section_pdf"))
        self._multi_file_widget(body, self.pdf_paths, "PDF").pack(fill="x", pady=(0, 14))

        # ── Notes-kolom keuze ─────────────────────────────────────────────────
        _section_label(body, 3, t("section_notes_col"))

        opts = tk.Frame(body, bg=BG)
        opts.pack(fill="x", pady=(0, 0))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("CB.TCombobox",
                        fieldbackground=SURFACE2, background=SURFACE2,
                        foreground=TEXT, selectbackground=AVID_B,
                        selectforeground="white", arrowcolor=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        insertcolor=TEXT, relief="flat", padding=6)
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
        self.root.option_add("*TCombobox*Listbox.font",             f"{{{UI_FONT}}} 12")
        self.root.option_add("*TCombobox*Listbox.relief",           "flat")
        self.root.option_add("*TCombobox*Listbox.borderWidth",      "0")

        PICK = t("col_pick_placeholder")

        def _make_col_values(recent_key):
            base    = self.COMMON_COLS
            recents = [r for r in self._prefs_cache.get(recent_key, [])
                       if r not in base and r != "Auto"]
            return ["Auto"] + base + recents + [PICK]

        def _main_cb(parent, var, recent_key, width):
            cb = ttk.Combobox(parent, textvariable=var,
                              values=_make_col_values(recent_key),
                              state="readonly", width=width,
                              style="CB.TCombobox", font=(UI_FONT, 12))
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
                            text=t("hint_more_settings"),
                            bg=BG, fg=MUTED,
                            font=(UI_FONT, 11), cursor="arrow", anchor="w")
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
        self._clear_all = _clear_all  # ook bruikbaar buiten deze build-functie

        clear_cv = _rounded_btn(hint_row, t("btn_clear_all"), _clear_all,
                                bg=SURFACE2, hv=BORDER, fg=MUTED,
                                font=(UI_FONT, 11), px=11, py=4, r=8, pbg=BG)
        clear_cv.pack(side="right")

        # ── Verwerk-knop (afgeronde Canvas, full-width) ──────────────────────
        _VF = (UI_FONT, 16, "bold")
        _VH = 52   # hoogte
        _VR = 12   # hoek-radius
        self._btn_enabled = True
        self.btn = tk.Canvas(body, height=_VH, bd=0, highlightthickness=0, bg=BG, cursor="arrow")
        self.btn.pack(fill="x")

        def _draw_verwerk(label=None, darken=0.0, disabled=False):
            if label is None:
                label = t("btn_process")
            w = self.btn.winfo_width()
            if w < 2: return
            if disabled:
                _rrect(self.btn, w, _VH, _VR, SURFACE2, MUTED, label, _VF)
            else:
                # Gradient afgeleid van de huidige accentkleur (licht → donker)
                _rrect_gradient(self.btn, w, _VH, _VR,
                                ACCENT2, AVID_B_H, "#FFFFFF", label, _VF,
                                darken=darken)

        def _on_verwerk_resize(e):
            if self._btn_enabled: _draw_verwerk()
            else:                 _draw_verwerk(t("btn_busy"), disabled=True)

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
            font=(MONO_FONT, 11), relief="flat", bd=0, highlightthickness=0,
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
                       fill="white", font=(UI_FONT, 8, "bold"))
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
                              text=t("file_drop_hint"),
                              bg=SURFACE, fg="#A99CDC",
                              font=(UI_FONT, 11), anchor="w")
        status_lbl.pack(side="left", fill="x", expand=True)

        pick_fn = self._pick_ale if file_type == "ALE" else self._pick_pdf
        add_cv  = _rounded_btn(status_row, t("btn_choose"), pick_fn,
                               bg=SURFACE2, hv=BORDER, fg=TEXT,
                               font=(UI_FONT, 11), px=11, py=4, r=6,
                               pbg=SURFACE)
        add_cv.pack(side="right")

        def _refresh():
            for w in list_frame.winfo_children():
                w.destroy()

            n = len(paths_list)

            if n == 0:
                status_lbl.config(text=t("file_drop_hint"))
                list_host.pack_forget()
                sep_line.pack_forget()
            else:
                word = t("file_word_single") if n == 1 else t("file_word_plural")
                status_lbl.config(text=t("file_n_selected", n=n, word=word))

                for i, p in enumerate(paths_list):
                    row = tk.Frame(list_frame, bg=SURFACE, height=_ROW_H)
                    row.pack(fill="x")
                    row.pack_propagate(False)

                    # Badge
                    bc = tk.Canvas(row, width=32, height=18, bg=SURFACE,
                                   bd=0, highlightthickness=0)
                    bc.pack(side="left", padx=(10, 6), pady=10)
                    _row_badge = "AVB" if (file_type == "ALE" and Path(p).suffix.lower() == ".avb") else file_type
                    bc.create_rectangle(0, 0, 32, 18, fill=badge_color, outline="")
                    bc.create_text(16, 9, text=_row_badge,
                                   fill="white", font=(UI_FONT, 8, "bold"))

                    # Bestandsnaam
                    tk.Label(row, text=Path(p).name, bg=SURFACE, fg=TEXT,
                             font=(UI_FONT, 11), anchor="w").pack(
                                 side="left", fill="x", expand=True)

                    # × verwijderknop
                    def _rm(idx=i):
                        paths_list.pop(idx)
                        _refresh()

                    rm = tk.Label(row, text="×", bg=SURFACE, fg=MUTED,
                                  font=(UI_FONT, 14), cursor="arrow",
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

        lbl = tk.Label(inner, text=t("file_drop_hint"), bg=SURFACE, fg=MUTED,
                       font=(UI_FONT, 11), anchor="w", cursor="arrow")
        lbl.pack(side="left", fill="x", expand=True)
        setattr(self, lbl_attr, lbl)

        kies_cv = _rounded_btn(inner, t("btn_choose"), cmd,
                               bg=SURFACE2, hv=BORDER, fg=TEXT,
                               font=(UI_FONT, 10), px=10, py=4, r=8, pbg=SURFACE)
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
        paths = filedialog.askopenfilenames(title=t("dlg_pick_pdf"),
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
        paths = filedialog.askopenfilenames(title=t("dlg_pick_ale"),
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
            self.log(t("err_no_license"), "err")
            return
        if not self.pdf_paths:
            self.log(t("err_no_pdf"), "err"); return
        if not self.ale_paths:
            self.log(t("err_no_ale"), "err"); return
        self._btn_enabled = False
        self._draw_verwerk(t("btn_busy"), disabled=True)
        threading.Thread(target=self._process, daemon=True).start()

    def _process(self):
        try:
            # ── Stap 1: alle PDFs parsen en clips samenvoegen ────────────
            all_clips = {}
            for pdf_p in self.pdf_paths:
                clips = parse_pdf(pdf_p, self.log,
                                  write_pu=self.write_pu_in_notes.get(),
                                  write_afg=self.write_afg_in_notes.get())
                if clips is None:
                    # Onbekend formaat → layout mapper tonen op main thread
                    result_holder = [None]
                    done_event = threading.Event()
                    def _show_mapper(p=pdf_p, rh=result_holder, ev=done_event):
                        _show_layout_mapper(p, lambda mapped: (rh.__setitem__(0, mapped), ev.set()))
                    self.root.after(0, _show_mapper)
                    done_event.wait()
                    if result_holder[0]:
                        all_clips.update(result_holder[0])
                    continue
                all_clips.update(clips)

            n_pdf = len(self.pdf_paths)
            self.log(f"Totaal: {len(all_clips)} clips uit {n_pdf} PDF('s)", "info")

            # ── Stap 2: elk ALE verwerken en opslaan ─────────────────────
            _out_dir    = self.output_dir.get().strip()
            _out_suffix = self.output_suffix.get().strip() or "_updated_with_notes"
            out_paths = []

            for ale_p in self.ale_paths:
                if Path(ale_p).suffix.lower() == ".avb":
                    stem    = Path(ale_p).stem
                    out_dir = Path(_out_dir) if _out_dir else Path(ale_p).parent
                    out     = out_dir / f"{stem}{_out_suffix}.avb"
                    try:
                        out_dir.mkdir(parents=True, exist_ok=True)
                        process_avb(Path(ale_p), out, all_clips, self.log,
                                    write_rating=self.write_rating.get(),
                                    write_notes=self.write_notes.get(),
                                    star_format=self.star_format.get())
                    except Exception as _e:
                        self.log(f"Fout bij AVB '{Path(ale_p).name}': {_e}", "err")
                        continue
                    out_paths.append(out)
                    self.log(t("log_saved", name=out.name), "ok")
                    continue

                result, src_encoding = process_ale(ale_p, all_clips, self.log,
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
                                     pu_eigen_kolom=self.pu_eigen_kolom.get(),
                                     pu_eigen_kolom_naam=self.pu_eigen_kolom_naam.get(),
                                     afg_col=(self.afg_col.get()
                                              if self.write_afg_in_notes.get() else "Uit"),
                                     afg_position=self.afg_position.get(),
                                     general_notes_col=(self.general_notes_col.get()
                                                        if self.write_general_notes.get() else "Uit"),
                                     star_format=self.star_format.get(),
                                     scene_col=(self.scene_col.get()
                                                if self.write_scene.get() else "Uit"))
                stem    = Path(ale_p).stem
                out_dir = Path(_out_dir) if _out_dir else Path(ale_p).parent
                out     = out_dir / f"{stem}{_out_suffix}.ALE"
                # ALE wordt teruggeschreven in DEZELFDE encoding als de input
                # (UTF-8 of Mac Roman). Zo blijven accenten/umlauten (ä ö ü enz.)
                # correct op zowel moderne als oudere Avid.
                _UNICODE_MAP = {
                    '‘': "'", '’': "'",   # curly single quotes → '
                    '“': '"', '”': '"',   # curly double quotes → "
                    '–': '-', '—': '-',   # en-dash / em-dash → -
                    '…': '...',                 # ellipsis → ...
                    '·': '-', '•': '-',   # bullet/middot → -
                    ' ': ' ',                   # non-breaking space → space
                    '​': '',  '‌': '',     # zero-width spaces → remove
                }
                def _ale_safe(s):
                    out = []
                    for c in s:
                        # Variation selectors / emoji presentation modifiers weggooien
                        if '︀' <= c <= '️' or c == '️':
                            continue
                        # Bekende vervangingen
                        if c in _UNICODE_MAP:
                            out.append(_UNICODE_MAP[c])
                            continue
                        # Alle overige tekens (incl. accenten/umlauten) blijven intact
                        out.append(c)
                    return ''.join(out)

                # Optionele transliteratie van umlauten (ü→ue, ö→oe, ä→ae, ß→ss)
                _TRANSLIT = {
                    'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
                    'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
                }
                def _translit(s):
                    return ''.join(_TRANSLIT.get(c, c) for c in s)

                safe = _ale_safe(result)
                if self.translit_umlauts.get():
                    safe = _translit(safe)
                # Uitvoer-encoding: voorkeur wint; "auto" = zelfde als invoer.
                # Let op: bij pure-ASCII invoer is detectie onmogelijk — dan is
                # de voorkeursinstelling de enige betrouwbare keuze.
                _enc_pref = self.ale_encoding.get()
                out_encoding = src_encoding if _enc_pref in ("auto", "", None) else _enc_pref
                self.log(f"ALE-codering: {out_encoding}"
                         + (" (auto)" if _enc_pref in ("auto", "", None) else ""), "info")
                try:
                    result_bytes = safe.encode(out_encoding)
                except UnicodeEncodeError:
                    # Vangnet: transliteren en anders vervangen zodat de export nooit faalt
                    result_bytes = _translit(safe).encode(out_encoding, errors="replace")
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(result_bytes)
                except OSError:
                    out = Path.home() / "Desktop" / f"{stem}{_out_suffix}.ALE"
                    out.write_bytes(result_bytes)
                out_paths.append(out)
                self.log(t("log_saved", name=out.name), "ok")

            n_ale = len(out_paths)
            self.log(t("log_done_one") if n_ale == 1 else t("log_done_many", n=n_ale), "ok")
            if out_paths:
                # Na verwerken velden wissen: Uit / Vragen / Automatisch, na instelbare vertraging
                _mode  = self.clear_mode.get()
                _delay = max(0, int(self.clear_delay.get())) * 1000
                if _mode in ("vragen", "automatisch"):
                    def _do_clear():
                        if getattr(self, "_clear_all", None):
                            self._clear_all()
                    if _mode == "automatisch":
                        self.root.after(_delay, _do_clear)
                    else:
                        self.root.after(_delay, lambda: self._ask_clear_dialog(_do_clear))
                # Map met resultaat openen — alleen als de gebruiker dat wil
                if self.open_folder_after.get():
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
                self._draw_verwerk()
            self.root.after(0, _re_enable)

    def _ask_clear_dialog(self, on_clear):
        """Vraag of de velden gewist mogen worden: knoppen 'Wis' / 'Laat staan'."""
        dlg = tk.Toplevel(self.root)
        dlg.title(t("ask_clear_title"))
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text=t("ask_clear_msg"), bg=BG, fg=TEXT,
                 font=(UI_FONT, 12), wraplength=320,
                 justify="left").pack(padx=24, pady=(22, 16))
        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(anchor="e", padx=24, pady=(0, 18))
        def _keep():
            dlg.destroy()
        def _clear():
            dlg.destroy()
            on_clear()
        _rounded_btn(btn_row, t("btn_clear_no"), _keep,
                     bg=SURFACE2, hv=SURFACE, fg=TEXT,
                     font=(UI_FONT, 11), px=16, py=6, r=8, pbg=BG).pack(side="left", padx=(0, 8))
        _rounded_btn(btn_row, t("btn_clear_yes"), _clear,
                     bg=AVID_B, hv="#2a6fbd", fg="white",
                     font=(UI_FONT, 11, "bold"), px=16, py=6, r=8, pbg=BG).pack(side="left")
        dlg.update_idletasks()
        mw = self.root.winfo_x() + self.root.winfo_width()  // 2
        mh = self.root.winfo_y() + self.root.winfo_height() // 2
        dlg.geometry(f"+{mw - dlg.winfo_width()//2}+{mh - dlg.winfo_height()//2}")

    def _apply_appearance_live(self):
        """Pas lettertype, accentkleur en interfacegrootte direct toe (zonder herstart)."""
        import tkinter.font as _tkfont

        # Kleur-vervangkaart: oude accent-trio → nieuwe accent-trio
        _old_trio = ACCENT_THEMES.get(getattr(self, "_prev_accent", "paars"),
                                      ACCENT_THEMES["paars"])
        _apply_font(self.ui_font.get())
        _apply_accent(self.accent.get())
        _new_trio = (AVID_B, AVID_B_H, ACCENT2)
        color_swap = {_old_trio[i]: _new_trio[i] for i in range(3)}
        self._prev_accent = self.accent.get()

        # Schaal (direct op de fonts, per widget; onthoudt basisgrootte)
        self._scale = max(10, min(200, int(self.ui_scale.get()))) / 100.0

        _COLOR_OPTS = ('bg', 'background', 'fg', 'foreground', 'activebackground',
                       'activeforeground', 'highlightbackground', 'highlightcolor',
                       'selectcolor', 'troughcolor', 'insertbackground')

        def _remap_font(w):
            try:
                f = w.cget('font')
            except Exception:
                return
            if not f:
                return
            wid = str(w)
            base = self._font_base.get(wid)
            if base is None:
                try:
                    fo = _tkfont.Font(root=self.root, font=f)
                    base = (abs(int(fo.cget('size'))) or 11,
                            fo.cget('weight'), fo.cget('slant'))
                except Exception:
                    return
                self._font_base[wid] = base
            size, weight, slant = base
            scaled = max(6, round(size * self._scale))
            spec = [UI_FONT, scaled]
            if weight == 'bold':
                spec.append('bold')
            if slant == 'italic':
                spec.append('italic')
            try:
                w.config(font=tuple(spec))
            except Exception:
                pass

        def _walk(w):
            # Kleuren omwisselen
            for opt in _COLOR_OPTS:
                try:
                    val = str(w.cget(opt))
                except Exception:
                    continue
                if val in color_swap:
                    try:
                        w.config(**{opt: color_swap[val]})
                    except Exception:
                        pass
            _remap_font(w)
            for c in w.winfo_children():
                _walk(c)   # ook Toplevels (Voorkeuren) — in-place, niet herbouwen

        _walk(self.root)

        # Combobox-stijl: font meeschalen (aqua negeert per-widget font op comboboxen)
        try:
            _st = ttk.Style()
            _cb_size = max(6, round(12 * self._scale))
            _st.configure("CB.TCombobox", selectbackground=AVID_B,
                          font=(UI_FONT, _cb_size), padding=max(2, round(6 * self._scale)))
            _st.map("CB.TCombobox", selectbackground=[("readonly", SURFACE2)])
            self.root.option_add("*TCombobox*Listbox.font", f"{{{UI_FONT}}} {_cb_size}")
        except Exception:
            pass

        # Hoofdvenster meeschalen in breedte zodat brede content niet afkapt
        try:
            self._win_w = int(520 * self._scale)
            self._win_h = int(650 * self._scale)
            cur = self.root.geometry().split("+")[0]
            self.root.geometry(f"{self._win_w}x{max(self.root.winfo_height(), self._win_h)}")
        except Exception:
            pass

        if getattr(self, "_draw_verwerk", None):
            try: self._draw_verwerk()
            except Exception: pass
        if getattr(self, "_redraw_header", None):
            try: self._redraw_header()
            except Exception: pass
        for _bd in getattr(self, "_badges", []):
            try: _bd()
            except Exception: pass

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
