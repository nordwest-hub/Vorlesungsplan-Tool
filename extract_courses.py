import pdfplumber
import json
import re

DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]

CELL_PATTERN = re.compile(
    r'^(?P<name>\S+)\s+(?P<type>[VÜ])\.?\s*(?P<lecturer>\S+)\s+(?P<room>R\s*\S+)$'
)
FOOTNOTE_PATTERN = re.compile(r'^\d+\)$')


def fix_time(raw):
    """Korrigiert OCR-Tippfehler wie '8.1-0' -> '8.10' und wandelt '8.10' in '08:10' um."""
    raw = raw.strip().replace('-', '')
    h, m = raw.split('.')
    return f"{int(h):02d}:{m}"


def parse_cell(cell_text):
    """Zerlegt eine Tabellenzelle in einzelne Kurs-Einträge."""
    if not cell_text:
        return []

    lines = [l.strip() for l in cell_text.split('\n') if l.strip()]
    entries = []
    pending_note = None

    for line in lines:
        if FOOTNOTE_PATTERN.match(line):
            # Fußnotenverweis (z.B. "6)") gehört zum letzten Eintrag
            if entries:
                entries[-1]['footnote'] = line.rstrip(')')
            continue

        m = CELL_PATTERN.match(line)
        if m:
            entries.append({
                'name': m.group('name'),
                'type': 'Vorlesung' if m.group('type') == 'V' else 'Übung',
                'lecturer': m.group('lecturer'),
                'room': m.group('room').replace(' ', ''),
                'footnote': None,
                'note': None,
            })
        else:
            # Zeilen wie "n. bes. Plan", oder ein Eintrag mit Fußnote in derselben Zeile
            m2 = re.match(
                r'^(?P<name>\S+)\s+(?P<type>[VÜ])\.?\s*(?P<lecturer>\S+)\s+(?P<room>R\s*\S+)\s+(?P<foot>\d+\))$',
                line
            )
            if m2:
                entries.append({
                    'name': m2.group('name'),
                    'type': 'Vorlesung' if m2.group('type') == 'V' else 'Übung',
                    'lecturer': m2.group('lecturer'),
                    'room': m2.group('room').replace(' ', ''),
                    'footnote': m2.group('foot').rstrip(')'),
                    'note': None,
                })
            elif entries:
                # Zusätzliche Anmerkung zum letzten Eintrag (z.B. "n. bes. Plan")
                entries[-1]['note'] = line
            else:
                pending_note = line

    return entries


def extract_all(pdf_path):
    courses = []
    course_id = 1

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                # Erste Zeile = Kopfzeile mit Wochentagen
                header = table[0]
                day_columns = {}
                for col_idx, header_cell in enumerate(header):
                    if header_cell and header_cell.strip() in DAYS:
                        day_columns[col_idx] = DAYS.index(header_cell.strip())

                for row in table[1:]:
                    first_cell = row[0] or ''
                    # Erste Spalte: "Blocknummer\nStart\nEnde"
                    time_match = re.match(r'^\d+\s*\n([\d.\-]+)\s*\n([\d.\-]+)', first_cell)
                    if not time_match:
                        continue  # z.B. Legende/Fußzeile

                    start = fix_time(time_match.group(1))
                    end = fix_time(time_match.group(2))

                    for col_idx, day_idx in day_columns.items():
                        cell_text = row[col_idx] if col_idx < len(row) else None
                        for entry in parse_cell(cell_text):
                            courses.append({
                                'id': course_id,
                                'name': entry['name'],
                                'type': entry['type'],
                                'lecturer': entry['lecturer'],
                                'room': entry['room'],
                                'day': DAYS[day_idx],
                                'start': start,
                                'end': end,
                                'footnote': entry['footnote'],
                                'note': entry['note'],
                                'page': page_index,
                            })
                            course_id += 1

    return courses


def dedupe(courses):
    """Entfernt Duplikate, die durch mehrere identische Wochen (Seiten) entstehen."""
    seen = {}
    result = []
    for c in courses:
        key = (c['name'], c['type'], c['lecturer'], c['room'], c['day'], c['start'], c['end'])
        if key in seen:
            continue
        seen[key] = True
        result.append(c)
    for i, c in enumerate(result, start=1):
        c['id'] = i
        del c['page']
        type_short = 'V' if c['type'] == 'Vorlesung' else 'Ü'
        c['label'] = f"{c['name']} {type_short} ({c['lecturer']})"
    return result


if __name__ == '__main__':
    courses = extract_all('sose_2026_vorlesungsplan_4._sem.pdf')
    courses = dedupe(courses)
    with open('courses.json', 'w', encoding='utf-8') as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)
    print(f"{len(courses)} eindeutige Kurs-Einträge extrahiert -> courses.json")
