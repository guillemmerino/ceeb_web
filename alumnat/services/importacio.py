# services/importacio.py
from dataclasses import dataclass
from typing import List, Optional, Tuple
from django.db import transaction
import pandas as pd
from pathlib import Path
from django.utils.dateparse import parse_date
from ..models import SeguimentAlumnat

SHEET_TO_FIELD = {
    "BC": "bc",
    "JOC": "cj",
    "GIO": "cg",
}

REQUIRED_COLS = ["Nif", "Correu electrònic", "Progres "]

@dataclass
class ImportResult:
    fulls_processats: List[str]
    creats: int
    actualitzats: int
    ignorats: int
    no_trobats: int
    errors: List[str]
    tret: str

def _clean_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return "" if s.lower() in ("nan", "none") else s

def extreure_tret_des_nom_fitxer(filename: str) -> str:
    import re
    stem = Path(filename).stem  # sense .xlsx
    # Busca el primer número (pot ser més d'una xifra)
    match = re.search(r"(\d+)", stem)
    if match:
        return match.group(1)
    return stem

def _split_cognoms(cognoms: str) -> Tuple[Optional[str], Optional[str]]:
    c = _clean_str(cognoms)
    if not c:
        return None, None
    c = c.split(",")[0].strip()
    parts = c.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])

def _parse_date_safe(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass

    if hasattr(v, "date"):
        try:
            return v.date()
        except Exception:
            pass

    d = parse_date(str(v))
    return d

def parse_progres_percent(v) -> Optional[float]:
    """
    Retorna percentatge com a número (0..100).
    Accepta: "83%", "83", 83, "0.83" (es considera 83%), 0.83.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    try:
        if s.endswith("%"):
            return float(s[:-1].replace(",", "."))
        x = float(s.replace(",", "."))
        # si ve com 0.83 -> 83
        return x * 100 if x <= 1 else x
    except ValueError:
        return None

@transaction.atomic
def importar_excel_seguiment(file_obj, sheet_choice: str = "ALL", llindar: float = 80.0) -> ImportResult:
    # IMPORTANT: aquest "tret" és el que omplirem a bc/cj/cg
    tret = extreure_tret_des_nom_fitxer(getattr(file_obj, "name", "fitxer"))

    xls = pd.ExcelFile(file_obj)

    if sheet_choice == "ALL":
        sheets = [s for s in xls.sheet_names if s in SHEET_TO_FIELD]
    else:
        sheets = [sheet_choice] if sheet_choice in xls.sheet_names else []

    actualitzats = ignorats = no_trobats = creats = 0
    errors: List[str] = []

    for sheet in sheets:
        df = pd.read_excel(xls, sheet_name=sheet)

        missing = [c for c in REQUIRED_COLS if c not in df.columns]
        if missing:
            errors.append(f"Full {sheet}: falten columnes: {', '.join(missing)}")
            continue

        camp_model = SHEET_TO_FIELD[sheet]  # "bc" / "cj" / "cg"

        
        # Troba la columna de "Progres" tolerant a espais
        progres_col = None
        for col in df.columns:
            if col.strip().lower() == "progres":
                progres_col = col
                break
        if not progres_col:
            # Si no troba, busca per substring
            for col in df.columns:
                if "progres" in col.strip().lower():
                    progres_col = col
                    break

        for idx, row in df.iterrows():
            rownum = idx + 2  # capçalera + 1

            nif = _clean_str(row.get("Nif", None))
            nom = _clean_str(row.get("Nom", None))
            cognoms = _clean_str(row.get("Cognoms", None))
            email = _clean_str(row.get("Correu electrònic", None)).lower()
            data_naixement = _parse_date_safe(row.get("Data naixement", None))
            progres = parse_progres_percent(row.get(progres_col)) if progres_col else None
            cognom1, cognom2 = _split_cognoms(cognoms)
            nom_i_cognom = " ".join([nom, cognoms]).strip() or None
            # si no podem identificar alumne -> ignorem
            if not nif and not email:
                ignorats += 1
                errors.append(f"WARNING: {nom_i_cognom}: ignorat (sense identificador: nif ni email) a {sheet}")
                continue

            # si no hi ha progres vàlid -> ignorem
            if progres is None:
                ignorats += 1
                errors.append(f"WARNING: {nom_i_cognom}: ignorat (progrés no vàlid) a {sheet}")
                continue

            # si no supera el llindar -> ignorem
            if progres <= llindar:
                ignorats += 1
                errors.append(f"WARNING: {nom_i_cognom}: ignorat (progrés {progres} ≤ {llindar}) a {sheet}")
                continue

            try:
                # === MATCHING SEGUR ===
                obj = None

                # 1) per NIF
                if nif:
                    qs = SeguimentAlumnat.objects.filter(document__iexact=nif)
                    if qs.count() == 1:
                        obj = qs.first()
                    elif qs.count() > 1:
                        errors.append(f"Full {sheet}, alumne {nom_i_cognom}: NIF duplicat a BD ({nif}). No s'actualitza.")
                        ignorats += 1
                        continue

                # 2) fallback per correu només si no hi ha NIF i és únic
                if obj is None and (not nif) and email:
                    qs = SeguimentAlumnat.objects.filter(correu__iexact=email)
                    if qs.count() == 1:
                        obj = qs.first()
                    elif qs.count() > 1:
                        errors.append(f"Full {sheet}, alumne {nom_i_cognom}: correu duplicat a BD ({email}). No s'actualitza.")
                        ignorats += 1
                        continue

                is_new = False
                if obj is None:
                    # CREEM registre nou
                    obj = SeguimentAlumnat(
                        document=nif or None,
                        correu=email or None,
                    )
                    is_new = True

                # === ACTUALITZACIÓ DE DADES PERSONALS (si venen informades) ===
                changed_fields = set()

                if nif and (obj.document or "").strip().lower() != nif.lower():
                    obj.document = nif
                    changed_fields.add("document")

                if email and (obj.correu or "").strip().lower() != email:
                    obj.correu = email
                    changed_fields.add("correu")

                if nom and (obj.nom or "") != nom:
                    obj.nom = nom
                    changed_fields.add("nom")

                if cognom1 and (obj.cognom1 or "") != cognom1:
                    obj.cognom1 = cognom1
                    changed_fields.add("cognom1")

                # cognom2 només si ve informat
                if cognom2 and (obj.cognom2 or "") != cognom2:
                    obj.cognom2 = cognom2
                    changed_fields.add("cognom2")

                if nom_i_cognom and (obj.nom_i_cognom or "") != nom_i_cognom:
                    obj.nom_i_cognom = nom_i_cognom
                    changed_fields.add("nom_i_cognom")

                if data_naixement and obj.data_naixement != data_naixement:
                    obj.data_naixement = data_naixement
                    changed_fields.add("data_naixement")

                # === ACTUALITZACIÓ DEL BLOC (bc/cj/cg) NOMÉS SI progres > llindar ===
                if progres is not None and progres > llindar:
                    valor_actual = getattr(obj, camp_model) or ""
                    if valor_actual != tret:
                        setattr(obj, camp_model, tret)
                        changed_fields.add(camp_model)

                # === GUARDAT ===
                if is_new:
                    obj.save()  # cal save complet en creació
                    creats += 1
                else:
                    if changed_fields:
                        obj.save(update_fields=list(changed_fields))
                        actualitzats += 1

            except Exception as e:
                errors.append(f"Full{sheet} {nom_i_cognom}: error ({e})")

    return ImportResult(
        fulls_processats=sheets,
        creats=creats,
        actualitzats=actualitzats,
        ignorats=ignorats,
        no_trobats=no_trobats,
        errors=errors,
        tret=tret,
    )
