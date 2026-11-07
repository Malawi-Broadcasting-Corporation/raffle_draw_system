"""The single way entries get into a draw: file uploads, API pulls and (later) pushes.

Every import is recorded as an ImportBatch. The third-party platform sends only a phone
number and a name per SMS (no message IDs), so each accepted row is one entry. Duplicate
protection works per batch: the same file can't be imported twice into a draw, and each API
pull only returns entries since the previous pull.
"""
import csv
import hashlib
import io
import json
from dataclasses import dataclass, field

from app.extensions import db
from app.models import Draw, ImportBatch, Participant, WhitelistEntry
from app.utils.phone import PhoneError, is_scientific, normalize_phone

ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'json'}
PHONE_HEADERS = ('phone', 'phone_number', 'phonenumber', 'msisdn', 'mobile', 'number', 'contact')
NAME_HEADERS = ('name', 'full_name', 'fullname', 'customer_name', 'participant')
MAX_REPORTED_PROBLEMS = 50

EXCLUDED_NOT_ON_WHITELIST = 'not_on_whitelist'
EXCLUDED_AFTER_LOCK = 'received_after_lock'


class ImportRejected(Exception):
    """The whole import was refused; nothing was saved."""


@dataclass
class RawRow:
    line: int          # row number as the user sees it in their file (1-based, incl. header)
    phone: object
    name: object = None


@dataclass
class ImportSummary:
    batch_id: int
    total: int
    accepted: int
    excluded: int
    rejected: int
    problems: list = field(default_factory=list)  # [{'line', 'value', 'reason'}]

    def message(self):
        parts = [f"{self.accepted} entries added"]
        if self.excluded:
            parts.append(f"{self.excluded} stored but not eligible")
        if self.rejected:
            parts.append(f"{self.rejected} rows rejected")
        return ', '.join(parts)

    def to_dict(self):
        return {**self.__dict__, 'message': self.message()}


# ---------------------------------------------------------------- reading files

def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return None if value == '' or value.lower() == 'nan' else value


def _from_table(table):
    """table: list of rows (lists of strings). Detects an optional header row."""
    table = [r for r in table if any(_clean(c) for c in r)]
    if not table:
        return []

    header = [(_clean(c) or '').lower().replace(' ', '_') for c in table[0]]
    phone_col = next((header.index(h) for h in PHONE_HEADERS if h in header), None)
    name_col = next((header.index(h) for h in NAME_HEADERS if h in header), None)
    has_header = phone_col is not None

    if not has_header:
        # No recognised header: phone is the first column, name the second if present.
        # A first row that isn't a phone number is treated as an unknown header.
        phone_col, name_col = 0, (1 if len(table[0]) > 1 else None)
        try:
            normalize_phone(table[0][0])
        except PhoneError as e:
            if e.code not in ('scientific_notation',):
                has_header = True

    start = 1 if has_header else 0
    rows = []
    for i, r in enumerate(table[start:], start=start + 1):
        phone = r[phone_col] if phone_col < len(r) else None
        name = r[name_col] if name_col is not None and name_col < len(r) else None
        rows.append(RawRow(line=i, phone=_clean(phone), name=_clean(name)))
    return rows


def _read_csv(data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('latin-1')
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return _from_table(list(csv.reader(io.StringIO(text), dialect)))


def _read_excel(data):
    import pandas as pd  # heavy import, only needed for Excel
    df = pd.read_excel(io.BytesIO(data), header=None, dtype=str, engine='openpyxl')
    return _from_table(df.fillna('').values.tolist())


def rows_from_json(payload):
    """Accepts a list of numbers, a list of objects, or those nested under data/results/participants."""
    if isinstance(payload, dict):
        for key in ('phone_numbers', 'data', 'results', 'participants', 'entries'):
            if key in payload:
                return rows_from_json(payload[key])
        raise ImportRejected("JSON format not recognised: expected a list of entries")
    if not isinstance(payload, list):
        raise ImportRejected("JSON format not recognised: expected a list of entries")

    rows = []
    for i, item in enumerate(payload, start=1):
        if isinstance(item, dict):
            lowered = {str(k).lower(): v for k, v in item.items()}
            phone = next((lowered[h] for h in PHONE_HEADERS if lowered.get(h) not in (None, '')), None)
            name = next((lowered[h] for h in NAME_HEADERS if lowered.get(h) not in (None, '')), None)
            rows.append(RawRow(line=i, phone=_clean(phone), name=_clean(name)))
        else:
            rows.append(RawRow(line=i, phone=_clean(item)))
    return rows


def read_file(filename, data):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        hint = " Open it in Excel and save as .xlsx." if ext == 'xls' else ''
        raise ImportRejected(f"Unsupported file type. Use CSV, Excel (.xlsx) or JSON.{hint}")
    try:
        if ext == 'csv':
            return _read_csv(data)
        if ext == 'json':
            return rows_from_json(json.loads(data.decode('utf-8-sig')))
        return _read_excel(data)
    except ImportRejected:
        raise
    except Exception as e:
        raise ImportRejected(f"Could not read the file: {e}") from e


# ---------------------------------------------------------------- importing

def check_not_scientific(rows):
    """Refuse the whole import if Excel has mangled any number. Partial imports would hide the damage."""
    bad = [r for r in rows if r.phone is not None and is_scientific(r.phone)]
    if bad:
        lines = ', '.join(str(r.line) for r in bad[:10])
        more = f" and {len(bad) - 10} more" if len(bad) > 10 else ''
        raise ImportRejected(
            f"{len(bad)} phone numbers are in scientific notation (e.g. '{bad[0].phone}' on row "
            f"{bad[0].line}), which means Excel has already lost their digits. Rows: {lines}{more}. "
            "Export the file again with the phone column formatted as Text. Nothing was imported."
        )


def whitelist_phones(draw_id):
    return {p for (p,) in db.session.query(WhitelistEntry.phone_number)
            .filter(WhitelistEntry.draw_id == draw_id)}


def import_entries(draw_id, rows, source, filename=None, file_bytes=None, user_id=None):
    """Validate and store entries for one draw as a single batch. Returns an ImportSummary."""
    draw = db.session.get(Draw, draw_id)
    if not draw:
        raise ImportRejected("Draw not found")

    # Late entries. A file upload can simply be refused, but an API pull can't be repeated
    # (each pull only returns entries since the last one), so late API entries are kept on
    # record as not eligible rather than lost.
    late_reason = None
    if draw.is_locked or draw.status in ('completed', 'cancelled'):
        if source != 'api':
            raise ImportRejected("Entries for this draw are locked; no more entries can be added")
        late_reason = EXCLUDED_AFTER_LOCK

    if source != 'api':  # API rows are rejected one by one instead, so a pull is never lost
        check_not_scientific(rows)

    file_hash = hashlib.sha256(file_bytes).hexdigest() if file_bytes is not None else None
    if file_hash:
        earlier = ImportBatch.query.filter_by(draw_id=draw_id, file_sha256=file_hash).first()
        if earlier:
            raise ImportRejected(
                f"This exact file was already imported into this draw on "
                f"{earlier.created_at:%d %b %Y %H:%M} ({earlier.filename}). Nothing was imported."
            )

    allowed = whitelist_phones(draw_id) if draw.whitelist_enabled else None
    batch = ImportBatch(draw_id=draw_id, source=source, filename=filename,
                        file_sha256=file_hash, created_by=user_id)
    db.session.add(batch)
    db.session.flush()

    accepted = excluded = 0
    problems = []
    for row in rows:
        try:
            phone = normalize_phone(row.phone)
        except PhoneError as e:
            if len(problems) < MAX_REPORTED_PROBLEMS:
                problems.append({'line': row.line, 'value': row.phone, 'reason': str(e)})
            continue

        reason = late_reason
        if reason is None and allowed is not None and phone not in allowed:
            reason = EXCLUDED_NOT_ON_WHITELIST
        if reason:
            excluded += 1
        else:
            accepted += 1
        db.session.add(Participant(
            draw_id=draw_id, phone_number=phone, name=(row.name or None) and str(row.name)[:150],
            source=source, batch_id=batch.id, excluded_reason=reason,
        ))

    rejected = len(rows) - accepted - excluded
    batch.rows_total = len(rows)
    batch.rows_accepted = accepted
    batch.rows_excluded = excluded
    batch.rows_rejected = rejected
    db.session.commit()

    return ImportSummary(batch_id=batch.id, total=len(rows), accepted=accepted,
                         excluded=excluded, rejected=rejected, problems=problems)


def import_file(draw_id, filename, data, user_id=None):
    if not data:
        raise ImportRejected("The file is empty")
    rows = read_file(filename, data)
    if not rows:
        raise ImportRejected("No rows found in the file")
    return import_entries(draw_id, rows, source='upload', filename=filename,
                          file_bytes=data, user_id=user_id)
