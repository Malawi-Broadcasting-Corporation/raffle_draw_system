"""Per-draw whitelists: only listed numbers can win (issue #5).

Entries from other numbers are kept on record but marked `not_on_whitelist`. Whenever the
list or the draw's whitelist setting changes, existing entries are re-checked, so the order
of "upload entries" and "upload whitelist" doesn't matter. Everything is frozen once the
draw's entry list is locked.
"""
from app.extensions import db
from app.models import ENTRY_MODES, Draw, Participant, WhitelistEntry
from app.services.import_service import (
    EXCLUDED_NOT_ON_WHITELIST, MAX_REPORTED_PROBLEMS, ImportRejected, check_not_scientific,
    read_file,
)
from app.utils.phone import PhoneError, normalize_phone


def _editable_draw(draw_id):
    draw = db.session.get(Draw, draw_id)
    if not draw:
        raise ImportRejected("Draw not found")
    if draw.is_locked or draw.winners:
        raise ImportRejected("This draw's entries are locked; its settings can no longer change")
    return draw


def refresh_exclusions(draw):
    """Re-apply the whitelist to every entry of the draw. Returns (newly excluded, newly allowed)."""
    base = Participant.query.filter(Participant.draw_id == draw.id)
    listed = db.session.query(WhitelistEntry.phone_number).filter(WhitelistEntry.draw_id == draw.id)

    if draw.whitelist_enabled:
        excluded = (base.filter(Participant.excluded_reason.is_(None),
                                ~Participant.phone_number.in_(listed))
                    .update({'excluded_reason': EXCLUDED_NOT_ON_WHITELIST}, synchronize_session=False))
        allowed = (base.filter(Participant.excluded_reason == EXCLUDED_NOT_ON_WHITELIST,
                               Participant.phone_number.in_(listed))
                   .update({'excluded_reason': None}, synchronize_session=False))
    else:
        excluded = 0
        allowed = (base.filter(Participant.excluded_reason == EXCLUDED_NOT_ON_WHITELIST)
                   .update({'excluded_reason': None}, synchronize_session=False))
    return excluded, allowed


def replace_whitelist(draw_id, filename, data):
    """Replace the draw's whitelist with the numbers in the file and switch the whitelist on."""
    draw = _editable_draw(draw_id)
    if not data:
        raise ImportRejected("The file is empty")
    rows = read_file(filename, data)
    if not rows:
        raise ImportRejected("No rows found in the file")
    check_not_scientific(rows)

    phones, problems, duplicates = {}, [], 0
    for row in rows:
        try:
            phone = normalize_phone(row.phone)
        except PhoneError as e:
            if len(problems) < MAX_REPORTED_PROBLEMS:
                problems.append({'line': row.line, 'value': row.phone, 'reason': str(e)})
            continue
        if phone in phones:
            duplicates += 1
            continue
        phones[phone] = row.name

    if not phones:
        raise ImportRejected("No valid phone numbers in the file. Nothing was changed.")

    WhitelistEntry.query.filter_by(draw_id=draw.id).delete()
    db.session.add_all(WhitelistEntry(draw_id=draw.id, phone_number=p, name=(n or None) and str(n)[:150])
                       for p, n in phones.items())
    draw.whitelist_enabled = True
    db.session.flush()
    excluded, allowed = refresh_exclusions(draw)
    db.session.commit()

    rejected = len(rows) - len(phones) - duplicates
    message = f"Whitelist saved with {len(phones)} numbers"
    if rejected:
        message += f", {rejected} rows rejected"
    return {
        'numbers': len(phones),
        'duplicates': duplicates,
        'rejected': rejected,
        'problems': problems,
        'entries_excluded': excluded,
        'entries_allowed': allowed,
        'message': message,
    }


def clear_whitelist(draw_id):
    """Remove the whitelist and switch it off; all entries become eligible again."""
    draw = _editable_draw(draw_id)
    WhitelistEntry.query.filter_by(draw_id=draw.id).delete()
    draw.whitelist_enabled = False
    _, allowed = refresh_exclusions(draw)
    db.session.commit()
    return {'entries_allowed': allowed, 'message': 'Whitelist removed'}


def update_draw_rules(draw_id, entry_mode=None, whitelist_enabled=None):
    """Change entry mode / whitelist switch. Only possible before the entry list is locked."""
    draw = _editable_draw(draw_id)
    if entry_mode is not None:
        if entry_mode not in ENTRY_MODES:
            raise ImportRejected(f"entry_mode must be one of {', '.join(ENTRY_MODES)}")
        draw.entry_mode = entry_mode
    if whitelist_enabled is not None:
        if whitelist_enabled and not WhitelistEntry.query.filter_by(draw_id=draw.id).first():
            raise ImportRejected("Upload a whitelist before switching it on")
        draw.whitelist_enabled = bool(whitelist_enabled)
    refresh_exclusions(draw)
    db.session.commit()
    return draw


def whitelist_summary(draw_id):
    draw = db.session.get(Draw, draw_id)
    if not draw:
        raise ImportRejected("Draw not found")
    count = WhitelistEntry.query.filter_by(draw_id=draw_id).count()
    excluded = Participant.query.filter_by(draw_id=draw_id,
                                           excluded_reason=EXCLUDED_NOT_ON_WHITELIST).count()
    return {'enabled': draw.whitelist_enabled, 'numbers': count, 'entries_excluded': excluded}
