# app/routes/draws.py
from functools import wraps
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required
from app.extensions import db
from app.models import Draw, Winner, Participant
from app.services import draw_service
from app.services.draw_service import DrawError
from app.utils.security import audit_log, admin_required
from app.services.prize_service import summarize_prizes

draws_bp = Blueprint('draws', __name__)


def _ok(**payload):
    return jsonify({'success': True, **payload})


def _fail(message, status=400):
    return jsonify({'success': False, 'message': message}), status


def handle_draw_errors(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except DrawError as e:
            return _fail(str(e))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Draw operation failed")
            return _fail("Unexpected error, check the server logs", 500)
    return wrapper


@draws_bp.route('/api/draws/<int:draw_id>/start', methods=['POST'])
@login_required
@audit_log('Start draw')
@handle_draw_errors
def start_draw(draw_id):
    return _ok(state=draw_service.start_draw(draw_id))


@draws_bp.route('/api/draws/<int:draw_id>/lock', methods=['POST'])
@login_required
@audit_log('Lock entry list')
@handle_draw_errors
def lock_draw(draw_id):
    return _ok(state=draw_service.lock_draw(draw_id))


@draws_bp.route('/api/draws/<int:draw_id>/unlock', methods=['POST'])
@login_required
@admin_required
@audit_log('Unlock entry list')
@handle_draw_errors
def unlock_draw(draw_id):
    return _ok(state=draw_service.unlock_draw(draw_id))


@draws_bp.route('/api/draws/<int:draw_id>/seed/drand', methods=['POST'])
@login_required
@audit_log('Take drand seed')
@handle_draw_errors
def seed_drand(draw_id):
    return _ok(state=draw_service.seed_from_drand(draw_id))


@draws_bp.route('/api/draws/<int:draw_id>/seed/manual', methods=['POST'])
@login_required
@audit_log('Enter manual seed')
@handle_draw_errors
def seed_manual(draw_id):
    data = request.get_json(silent=True) or {}
    return _ok(state=draw_service.seed_manually(draw_id, data.get('seed'), data.get('reference')))


@draws_bp.route('/api/draws/<int:draw_id>/replay')
@login_required
@handle_draw_errors
def replay_draw(draw_id):
    result = draw_service.replay_draw(draw_id)
    result['picks'] = [dict(zip(('position', 'expected_entry', 'recorded_entry', 'ok'), p))
                       for p in result['picks']]
    result['all_ok'] = result['fingerprint_ok'] and all(p['ok'] for p in result['picks'])
    return _ok(replay=result)


@draws_bp.route('/api/draws/<int:draw_id>/stop', methods=['POST'])
@login_required
@audit_log('Stop draw')
@handle_draw_errors
def stop_draw(draw_id):
    return _ok(state=draw_service.stop_draw(draw_id))


@draws_bp.route('/api/draws/<int:draw_id>/draw-winner', methods=['POST'])
@login_required
@audit_log('Draw winner')
@handle_draw_errors
def draw_winner(draw_id):
    return _ok(winner=draw_service.draw_next_winner(draw_id))


@draws_bp.route('/api/winners/<int:winner_id>/void', methods=['POST'])
@login_required
@audit_log('Void winner')
@handle_draw_errors
def void_winner(winner_id):
    reason = (request.get_json(silent=True) or {}).get('reason', 'other')
    return _ok(state=draw_service.void_winner(winner_id, reason))


@draws_bp.route('/api/winners/<int:winner_id>/confirm', methods=['POST'])
@login_required
@audit_log('Confirm winner')
@handle_draw_errors
def confirm_winner(winner_id):
    return _ok(state=draw_service.confirm_winner(winner_id))


@draws_bp.route('/api/draws/<int:draw_id>/summary')
@login_required
@handle_draw_errors
def draw_summary(draw_id):
    return _ok(state=draw_service.get_state(draw_id), summary=draw_service.control_summary(draw_id))


# Public: the TV screen polls these
@draws_bp.route('/api/draws/<int:draw_id>/state')
@handle_draw_errors
def draw_state(draw_id):
    return _ok(state=draw_service.get_state(draw_id))


@draws_bp.route('/api/draws/<int:draw_id>/animation')
@handle_draw_errors
def draw_animation(draw_id):
    return _ok(sequence=draw_service.get_animation_numbers(draw_id))


def _draw_row(draw, counts):
    return {
        'id': draw.id,
        'name': draw.name,
        'status': draw.status,
        'currency': draw.currency,
        'total_winners': draw.total_winners,
        'prize_summary': summarize_prizes(draw.prizes),
        'participant_count': counts.get(draw.id, 0),
        'entry_mode': draw.entry_mode,
        'whitelist_enabled': draw.whitelist_enabled,
        'locked': draw.is_locked,
        'seeded': bool(draw.seed),
        'created_at': draw.created_at.isoformat() if draw.created_at else None,
    }


@draws_bp.route('/')
@login_required
def management():
    counts = draw_service.participant_counts()
    draws = Draw.query.order_by(Draw.created_at.desc()).all()
    return render_template('management.html', draws=[_draw_row(d, counts) for d in draws])


@draws_bp.route('/api/draws')
@login_required
def get_draws():
    counts = draw_service.participant_counts()
    draws = Draw.query.order_by(Draw.created_at.desc()).all()
    return jsonify([_draw_row(d, counts) for d in draws])


@draws_bp.route('/api/draws/live')
@handle_draw_errors
def live_draw():
    live = _live_draw()
    return _ok(state=draw_service.get_state(live.id) if live else None)


def _live_draw():
    """The draw the on-air screen should follow: the active one, else the most recently locked one.

    Falling back to the locked draw keeps the screen on the same draw while it is paused
    for a live call, and shows the results once it completes.
    """
    return (Draw.query.filter_by(status='active').first()
            or Draw.query.filter(Draw.locked_at.isnot(None), Draw.status != 'cancelled')
            .order_by(Draw.locked_at.desc()).first())


@draws_bp.route('/api/winners')
@login_required
def get_winners():
    limit = min(request.args.get('limit', 10, type=int), 100)
    winners = Winner.query.order_by(Winner.won_at.desc()).limit(limit).all()
    return jsonify([{
        'id': w.id,
        'phone_number': w.participant.phone_number,
        'prize': w.prize.name,
        'draw_name': w.draw.name,
        'position': w.position,
        'status': w.status,
        'won_at': w.won_at.isoformat() if w.won_at else None,
    } for w in winners])


@draws_bp.route('/tv')
@draws_bp.route('/tv/<int:draw_id>')
def tv_display(draw_id=None):
    pinned = draw_id is not None
    state = None
    try:
        if draw_id is None:
            live = _live_draw()
            draw_id = live.id if live else None
        if draw_id:
            state = draw_service.get_state(draw_id)
    except DrawError:
        state = None
    return render_template('tv_display.html', current_draw=state, pinned=pinned)
