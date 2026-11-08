"""Read incident snapshots without inventing unreported service windows."""

import csv
import hashlib
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .pipeline import normalize

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def workbook_rows(payload):
    """Read values from XLSX (including sparse cells); no formula evaluation."""
    with zipfile.ZipFile(io.BytesIO(payload)) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared = [
                "".join(n.text or "" for n in item.findall(".//m:t", NS))
                for item in ET.fromstring(book.read("xl/sharedStrings.xml"))
            ]
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        props = workbook.find("m:workbookPr", NS)
        epoch = datetime(1904, 1, 1) if props is not None and props.get("date1904") in {"1", "true"} else datetime(1899, 12, 30)
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
        for sheet in workbook.findall("m:sheets/m:sheet", NS):
            target = rels[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            header = None
            for _, row in ET.iterparse(book.open(target), events=("end",)):
                if row.tag != "{" + NS["m"] + "}row":
                    continue
                cells = {}
                for cell in row.findall("m:c", NS):
                    column = re.match(r"[A-Z]+", cell.get("r")).group()
                    value = cell.findtext("m:v", "", NS)
                    if cell.find("m:f", NS) is not None:
                        raise ValueError("Formula cells require a reviewed export")
                    if cell.get("t") == "s":
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(n.text or "" for n in cell.findall(".//m:t", NS))
                    cells[column] = value
                if header is None:
                    header = cells
                    if not {"Date", "Route", "Time", "Incident", "Min Delay"} <= set(header.values()):
                        raise ValueError("Unsupported workbook sheet: " + sheet.get("name"))
                elif any(cells.values()):
                    record = {name: cells.get(column, "") for column, name in header.items()}
                    value = record["Date"]
                    if re.fullmatch(r"\d+(\.\d+)?", value):
                        record["Date"] = (epoch + timedelta(days=float(value))).date().isoformat()
                    value = record["Time"]
                    if re.fullmatch(r"0(\.\d+)?", value):
                        seconds = round(float(value) * 86400)
                        record["Time"] = f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
                    record["_sheet"] = sheet.get("name")
                    yield record
                row.clear()


def source_rows(path):
    payload = path.read_bytes()
    if path.name.lower().endswith(".xlsx.zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as outer:
            names = [n for n in outer.namelist() if n.lower().endswith(".xlsx") and not n.startswith("__MACOSX/")]
            if len(names) != 1:
                raise ValueError("Expected one workbook per ZIP")
            yield from workbook_rows(outer.read(names[0]))
    elif path.suffix.lower() == ".xlsx":
        yield from workbook_rows(payload)
    elif path.suffix.lower() == ".csv":
        yield from csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    else:
        raise ValueError("Expected CSV, XLSX or .xlsx.zip")


def load_events(paths):
    records, sources, seen = [], [], set()
    for path in map(Path, paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        audit = {"name": path.name, "sha256": digest, "raw_rows": 0, "accepted": 0, "duplicates": 0}
        rejected = Counter()
        for number, row in enumerate(source_rows(path), 2):
            audit["raw_rows"] += 1
            adapted = dict(row)
            adapted["Line"] = row.get("Line", row.get("Route", ""))
            adapted["Code"] = row.get("Code", row.get("Incident", ""))
            try:
                event = normalize(adapted, number, digest)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                rejected[str(exc)] += 1
                continue
            # Use source context too, so simultaneous distinguishable events survive.
            key = (event["route_id"], event["event_time"], event["code"], event["delay_minutes"],
                   row.get("Station", row.get("Location", "")), row.get("Min Gap", ""),
                   row.get("Bound", row.get("Direction", "")), row.get("Vehicle", ""))
            if key in seen:
                audit["duplicates"] += 1
                continue
            seen.add(key)
            event["hour"] = int(adapted["Time"].split(":")[0])
            records.append(event)
            audit["accepted"] += 1
        audit["quarantine_reasons"] = dict(rejected)
        sources.append(audit)
    if not records:
        raise ValueError("No valid incidents")
    return sorted(records, key=lambda r: (r["event_time"], r["route_id"])), sources
