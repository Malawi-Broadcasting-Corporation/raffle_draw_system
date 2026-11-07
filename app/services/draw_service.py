import secrets
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.services import checkable
from app.models import ENTRY_PER_NUMBER, Draw, Participant, Winner
from app.utils.phone import mask_phone

_rng = secrets.SystemRandom()


class DrawError(Exception):
    """Expected, user-facing problem (wrong state, nothing left to draw, ...)."""


def _get_draw(draw_id):
    draw = db.session.get(Draw, draw_id)
    if not draw:
        raise DrawError("Draw not found")
    return draw


def _complete(draw):
    draw.status = 'completed'
    draw.completed_at = datetime.utcnow()


def _prize_progress(draw):
    """[(prize, winners_taken)] in draw order. Void winners don't count."""
    counts = dict(
        db.session.query(Winner.prize_id, func.count(Winner.id))
        .filter(Winner.draw_id == draw.id, Winner.status != 'void')
        .group_by(Winner.prize_id)
        .all()
    )
    return [(p, counts.get(p.id, 0)) for p in draw.prizes]


def _eligible_filter(query, draw_id):
    """Entries that may win: verified and not excluded (e.g. not on the whitelist)."""
    return query.filter(
        Participant.draw_id == draw_id,
        Participant.is_verified.is_(True),
        Participant.excluded_reason.is_(None),
    )


def build_pool(draw):
    """The draw's tickets as [(participant_id, phone)], in a fixed order (phone, then id).

    per_sms:    every eligible entry is a ticket, so 3 SMS = 3 chances.
    per_number: one ticket per phone number (its earliest entry), however many SMS it sent.
    The fixed order matters for checkable draws: the same entries always give the same pool.
    """
    rows = (
        _eligible_filter(db.session.query(Participant.id, Participant.phone_number), draw.id)
        .order_by(Participant.phone_number, Participant.id)
        .all()
    )
    tickets = [(pid, phone) for pid, phone in rows]
    if draw.entry_mode == ENTRY_PER_NUMBER:
        seen = set()
        tickets = [t for t in tickets if not (t[1] in seen or seen.add(t[1]))]
    return tickets


def _won_phones(draw_id):
    """Every number that has won in this draw, including voided winners (they can't win again)."""
    rows = (
        db.session.query(Participant.phone_number)
        .join(Winner, Winner.participant_id == Participant.id)
        .filter(Winner.draw_id == draw_id)
        .all()
    )
    return {r[0] for r in rows}


def eligible_number_count(draw):
    """Distinct numbers that could still win (each number wins at most once)."""
    won = _won_phones(draw.id)
    return len({phone for _, phone in build_pool(draw) if phone not in won})


def participant_counts():
    """{draw_id: number of eligible entries} for all draws."""
    rows = (
        db.session.query(Participant.draw_id, func.count(Participant.id))
        .filter(Participant.is_verified.is_(True), Participant.excluded_reason.is_(None))
        .group_by(Participant.draw_id)
        .all()
    )
    return dict(rows)


def _prize_dict(prize, nth=None):
    return {
        'id': prize.id, 'name': prize.name, 'type': prize.prize_type,
        'image_path': prize.image_path, 'quantity': prize.quantity, 'nth': nth,
    }


def get_state(draw_id):
    draw = _get_draw(draw_id)
    progress = _prize_progress(draw)
    total = sum(p.quantity for p, _ in progress)
    drawn = sum(min(t, p.quantity) for p, t in progress)
    upcoming = next(((p, t + 1) for p, t in progress if t < p.quantity), None)

    return {
        'draw_id': draw.id,
        'name': draw.name,
        'status': draw.status,
        'is_running': draw.status == 'active',
        'entry_mode': draw.entry_mode,
        'whitelist_enabled': draw.whitelist_enabled,
        'locked': draw.is_locked,
        'locked_at': draw.locked_at.isoformat() + 'Z' if draw.locked_at else None,
        'pool_size': draw.pool_size,
        'pool_fingerprint': draw.pool_fingerprint,
        'seeded': bool(draw.seed),
        'seed_source': draw.seed_source,
        'seed_reference': draw.seed_reference,
        'winners_drawn': drawn,
        'total_winners': total,
        'next_prize': _prize_dict(*upcoming) if upcoming else None,
        'prizes': [{**_prize_dict(p), 'drawn': min(t, p.quantity)} for p, t in progress],
    }


def _remaining_prizes(draw):
    return sum(p.quantity - t for p, t in _prize_progress(draw))


def _check_enough_numbers(draw):
    remaining = _remaining_prizes(draw)
    if remaining <= 0:
        raise DrawError("All prizes for this draw have already been drawn")
    eligible = eligible_number_count(draw)
    if eligible < remaining:
        raise DrawError(f"Not enough eligible numbers: {remaining} prizes left, "
                        f"{eligible} numbers that can still win")


def _verified_pool(draw):
    """The current pool, after checking it is exactly the pool that was locked."""
    pool = build_pool(draw)
    if checkable.fingerprint(pool) != draw.pool_fingerprint:
        raise DrawError("The entry list has changed since it was locked. The draw cannot continue; "
                        "check the audit log.")
    return pool


# ---------------------------------------------------------------- lock & seed (#6)

def lock_draw(draw_id):
    """Freeze the entry list and fingerprint it. Must happen before the seed is taken."""
    draw = _get_draw(draw_id)
    if draw.is_locked:
        raise DrawError("The entry list is already locked")
    if draw.status in ('completed', 'cancelled'):
        raise DrawError(f"Draw is {draw.status}")
    if not draw.prizes:
        raise DrawError("Add at least one prize before locking the draw")
    _check_enough_numbers(draw)

    pool = build_pool(draw)
    draw.locked_at = datetime.utcnow()
    draw.pool_size = len(pool)
    draw.pool_fingerprint = checkable.fingerprint(pool)
    db.session.commit()
    return get_state(draw_id)


def unlock_draw(draw_id):
    """Undo a lock made by mistake. Only allowed before the seed exists, so seeds can't be shopped for."""
    draw = _get_draw(draw_id)
    if not draw.is_locked:
        raise DrawError("The entry list is not locked")
    if draw.seed:
        raise DrawError("The seed has been taken; the draw can no longer be unlocked. Cancel it instead.")
    draw.locked_at = draw.pool_size = draw.pool_fingerprint = None
    db.session.commit()
    return get_state(draw_id)


def _store_seed(draw, value, source, reference):
    draw.seed, draw.seed_source, draw.seed_reference = value, source, reference[:255]
    db.session.commit()
    return get_state(draw.id)


def _seedable_draw(draw_id):
    draw = _get_draw(draw_id)
    if not draw.is_locked:
        raise DrawError("Lock the entry list before taking the seed")
    if draw.seed:
        raise DrawError("This draw already has a seed; it can never be changed")
    return draw


def seed_from_drand(draw_id, fetch=None):
    draw = _seedable_draw(draw_id)
    fetch = fetch or checkable.fetch_drand_seed
    try:
        value, reference = fetch(draw.locked_at)
    except checkable.SeedError as e:
        raise DrawError(str(e)) from e
    db.session.refresh(draw)
    draw = _seedable_draw(draw_id)  # re-check: another operator may have seeded while we waited
    return _store_seed(draw, value, 'drand', reference)


def seed_manually(draw_id, value, reference):
    draw = _seedable_draw(draw_id)
    try:
        value, reference = checkable.validate_manual_seed(value, reference)
    except checkable.SeedError as e:
        raise DrawError(str(e)) from e
    return _store_seed(draw, value, 'manual', reference)


# ---------------------------------------------------------------- running

def start_draw(draw_id):
    """Start or resume a draw. Needs a locked entry list and a seed."""
    draw = _get_draw(draw_id)
    if draw.status in ('completed', 'cancelled'):
        raise DrawError(f"Draw is {draw.status}")
    if not draw.is_locked:
        raise DrawError("Lock the entry list before starting the draw")
    if not draw.seed:
        raise DrawError("Take the seed (drand or manual) before starting the draw")

    live = Draw.query.filter(Draw.status == 'active', Draw.id != draw_id).first()
    if live:
        raise DrawError(f"Another draw is live: '{live.name}'. Pause it first.")

    _check_enough_numbers(draw)
    _verified_pool(draw)
    draw.status = 'active'
    db.session.commit()
    return get_state(draw_id)


def stop_draw(draw_id):
    """Pause a live draw. It can be resumed with start_draw."""
    draw = _get_draw(draw_id)
    if draw.status == 'active':
        draw.status = 'paused'
        db.session.commit()
    return get_state(draw_id)


def draw_next_winner(draw_id):
    for _ in range(3):  # retry if a concurrent click grabbed the same position
        draw = _get_draw(draw_id)
        if draw.status != 'active':
            raise DrawError("Draw is not active")

        progress = _prize_progress(draw)
        slot = next(((p, t + 1) for p, t in progress if t < p.quantity), None)
        if slot is None:
            _complete(draw)
            db.session.commit()
            raise DrawError("All prizes have already been drawn")
        prize, nth = slot

        pool = _verified_pool(draw)
        won = _won_phones(draw.id)
        if not any(phone not in won for _, phone in pool):
            raise DrawError("No eligible numbers left")

        position = (db.session.query(func.max(Winner.position))
                    .filter(Winner.draw_id == draw_id).scalar() or 0) + 1
        key = checkable.draw_key(draw.pool_fingerprint, draw.seed)
        chosen_id, _phone = checkable.pick(key, position, pool, won)
        total = sum(p.quantity for p, _ in progress)
        drawn_after = sum(t for _, t in progress) + 1

        db.session.add(Winner(draw_id=draw_id, participant_id=chosen_id,
                              prize_id=prize.id, position=position))
        if drawn_after >= total:
            _complete(draw)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            continue

        participant = db.session.get(Participant, chosen_id)
        return {
            'phone_number': participant.phone_number,
            'phone_masked': mask_phone(participant.phone_number),
            'name': participant.name,
            'prize': _prize_dict(prize, nth),
            'position': position,
            'winners_drawn': drawn_after,
            'total_winners': total,
            'draw_complete': drawn_after >= total,
        }

    raise DrawError("Draw is busy, please try again")


def replay_draw(draw_id):
    """Re-run a draw from its locked list and seed and compare with the recorded winners."""
    draw = _get_draw(draw_id)
    if not draw.is_locked or not draw.seed:
        raise DrawError("This draw has no locked list and seed to replay")
    pool = build_pool(draw)
    recorded = [
        (w.position, w.participant_id, w.participant.phone_number)
        for w in Winner.query.filter_by(draw_id=draw_id).order_by(Winner.position)
    ]
    current_fp = checkable.fingerprint(pool)
    return {
        'fingerprint_recorded': draw.pool_fingerprint,
        'fingerprint_now': current_fp,
        'fingerprint_ok': current_fp == draw.pool_fingerprint,
        'seed': draw.seed,
        'seed_source': draw.seed_source,
        'seed_reference': draw.seed_reference,
        'picks': checkable.replay(pool, draw.seed, recorded),
    }


VOID_REASONS = {'no_answer', 'ineligible', 'other'}


def void_winner(winner_id, reason='other'):
    """Disqualify a winner (unreachable, ineligible...). Their prize slot reopens for a redraw."""
    if reason not in VOID_REASONS:
        raise DrawError(f"Reason must be one of {', '.join(sorted(VOID_REASONS))}")
    winner = db.session.get(Winner, winner_id)
    if not winner:
        raise DrawError("Winner not found")
    if winner.status == 'void':
        raise DrawError("Winner is already void")

    winner.status = 'void'
    winner.void_reason = reason
    winner.status_changed_at = datetime.utcnow()
    draw = winner.draw
    if draw.status == 'completed':
        draw.status = 'paused'
        draw.completed_at = None
    db.session.commit()
    return get_state(draw.id)


def get_animation_numbers(draw_id, count=125):
    """Cosmetic only: masked numbers for the spinning display. Has no link to winner selection."""
    already_won = db.session.query(Winner.participant_id).filter(Winner.draw_id == draw_id)
    rows = (
        _eligible_filter(db.session.query(Participant.phone_number), draw_id)
        .filter(~Participant.id.in_(already_won))
        .order_by(func.random())
        .limit(count)
        .all()
    )
    phones = [mask_phone(r[0]) for r in rows]
    if not phones:
        return []
    phones += [_rng.choice(phones) for _ in range(count - len(phones))]
    return phones