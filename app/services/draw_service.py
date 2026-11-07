import secrets
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import Draw, Participant, Winner
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


def _eligible_ids(draw_id):
    """Verified participants who have never won in this draw (void winners stay excluded)."""
    already_won = db.session.query(Winner.participant_id).filter(Winner.draw_id == draw_id)
    rows = (
        db.session.query(Participant.id)
        .filter(Participant.draw_id == draw_id, Participant.is_verified.is_(True))
        .filter(~Participant.id.in_(already_won))
        .all()
    )
    return [r[0] for r in rows]


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
        'winners_drawn': drawn,
        'total_winners': total,
        'next_prize': _prize_dict(*upcoming) if upcoming else None,
        'prizes': [{**_prize_dict(p), 'drawn': min(t, p.quantity)} for p, t in progress],
    }


def start_draw(draw_id):
    """Start or resume a draw."""
    draw = _get_draw(draw_id)
    if draw.status in ('completed', 'cancelled'):
        raise DrawError(f"Draw is {draw.status}")
    if not draw.prizes:
        raise DrawError("Add at least one prize before starting the draw")

    live = Draw.query.filter(Draw.status == 'active', Draw.id != draw_id).first()
    if live:
        raise DrawError(f"Another draw is live: '{live.name}'. Pause it first.")

    remaining = sum(p.quantity - t for p, t in _prize_progress(draw))
    if remaining <= 0:
        raise DrawError("All prizes for this draw have already been drawn")

    eligible = len(_eligible_ids(draw_id))
    if eligible < remaining:
        raise DrawError(f"Not enough verified participants. Need {remaining}, have {eligible}")

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

        eligible = _eligible_ids(draw_id)
        if not eligible:
            raise DrawError("No eligible participants left")

        chosen_id = _rng.choice(eligible)
        position = (db.session.query(func.max(Winner.position))
                    .filter(Winner.draw_id == draw_id).scalar() or 0) + 1
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
            'prize': _prize_dict(prize, nth),
            'position': position,
            'winners_drawn': drawn_after,
            'total_winners': total,
            'draw_complete': drawn_after >= total,
        }

    raise DrawError("Draw is busy, please try again")


def void_winner(winner_id):
    """Disqualify a winner (unreachable, ineligible...). Their prize slot reopens for a redraw."""
    winner = db.session.get(Winner, winner_id)
    if not winner:
        raise DrawError("Winner not found")
    if winner.status == 'void':
        raise DrawError("Winner is already void")

    winner.status = 'void'
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
        db.session.query(Participant.phone_number)
        .filter(Participant.draw_id == draw_id, Participant.is_verified.is_(True))
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