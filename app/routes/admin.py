# app/routes/admin.py
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import (
    Draw, AuditLog, ImportBatch, Winner, WhitelistEntry, Prize, ENTRY_MODES, ENTRY_PER_SMS,
)
from app.utils.security import admin_required, audit_log
from datetime import datetime
from sqlalchemy import func
from app.services.draw_service import participant_counts
from app.services import whitelist_service
from app.services.import_service import ImportRejected
from app.services.prize_service import parse_prizes, summarize_prizes
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin')
@login_required
@admin_required
def admin_panel():
    try:
        draws = Draw.query.order_by(Draw.created_at.desc()).all()
        counts = participant_counts()
        draws_data = [{
            'id': draw.id,
            'name': draw.name,
            'prize_summary': summarize_prizes(draw.prizes),
            'total_winners': draw.total_winners,
            'status': draw.status,
            'participant_count': counts.get(draw.id, 0),
            'entry_mode': draw.entry_mode,
            'whitelist_enabled': draw.whitelist_enabled,
            'locked': draw.is_locked,
        } for draw in draws]
        return render_template('admin.html', draws=draws_data)
    except Exception as e:
        current_app.logger.error(f"Error in admin panel: {e}")
        return render_template('admin.html', draws=[])

@admin_bp.route('/admin/draws', methods=['POST'])
@login_required
@admin_required
@audit_log('Create draw')
def create_draw_route():
    try:
        data = request.get_json()
        currency = data.get('currency', 'MWK')

        raw_prizes = data.get('prizes')
        if not raw_prizes and data.get('prize_amount') is not None:
            # Legacy form: one cash prize x N winners (until the UI is updated)
            amount = float(data['prize_amount'])
            raw_prizes = [{
                'name': f"{currency} {amount:,.0f}", 'prize_type': 'cash', 'value': amount,
                'currency': currency, 'quantity': data.get('number_of_winners', 1),
            }]

        entry_mode = data.get('entry_mode', ENTRY_PER_SMS)
        if entry_mode not in ENTRY_MODES:
            raise ValueError(f"entry_mode must be one of {', '.join(ENTRY_MODES)}")

        draw = Draw(
            name=data['name'],
            description=data.get('description', ''),
            currency=currency,
            entry_mode=entry_mode,
            whitelist_enabled=bool(data.get('whitelist_enabled', False)),
            scheduled_for=(datetime.fromisoformat(data['scheduled_for'].replace('Z', '+00:00'))
                           if data.get('scheduled_for') else None),
        )
        draw.prizes = parse_prizes(raw_prizes)

        db.session.add(draw)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Draw created successfully', 'draw_id': draw.id})

    except KeyError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Missing field: {e}'}), 400
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating draw: {e}")
        return jsonify({'success': False, 'message': 'Error creating draw'}), 500


@admin_bp.route('/admin/draws/<int:draw_id>/prizes', methods=['PUT'])
@login_required
@admin_required
@audit_log('Update prizes')
def update_prizes(draw_id):
    draw = db.get_or_404(Draw, draw_id)
    if draw.is_locked or Winner.query.filter_by(draw_id=draw_id).first():
        return jsonify({'success': False,
                        'message': 'Prizes cannot be changed once the draw is locked'}), 409
    try:
        draw.prizes = parse_prizes((request.get_json() or {}).get('prizes'))
        db.session.commit()
        return jsonify({'success': True, 'message': 'Prizes updated'})
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@admin_bp.route('/admin/draws/<int:draw_id>', methods=['DELETE'])
@login_required
@admin_required
@audit_log('Delete draw')
def delete_draw(draw_id):
    try:
        draw = db.get_or_404(Draw, draw_id)

        # A draw that has been locked or has winners is part of the public record: cancel it instead.
        if draw.is_locked or draw.winners:
            return jsonify({'success': False,
                            'message': 'This draw has been locked or has winners and cannot be deleted'}), 409

        ImportBatch.query.filter_by(draw_id=draw_id).delete()
        WhitelistEntry.query.filter_by(draw_id=draw_id).delete()
        db.session.delete(draw)  # prizes and entries cascade
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Draw deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting draw: {e}")
        return jsonify({'success': False, 'message': f'Error deleting draw: {str(e)}'})

@admin_bp.route('/admin/settings')
@login_required
@admin_required
def settings():
    return render_template('settings.html')

@admin_bp.route('/admin/audit-logs')
@login_required
@admin_required
def audit_logs():
    try:
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(100).all()
        # Convert to list to avoid detached instance issues
        logs_data = []
        for log in logs:
            logs_data.append({
                'timestamp': log.timestamp,
                'user': log.user.username if log.user else 'System',
                'action': log.action,
                'details': log.details,
                'ip_address': log.ip_address
            })
        return render_template('audit_logs.html', logs=logs_data)
    except Exception as e:
        current_app.logger.error(f"Error getting audit logs: {e}")
        return render_template('audit_logs.html', logs=[])

@admin_bp.route('/api/stats')
@login_required
def get_stats():
    try:
        total_draws = Draw.query.count()
        completed_draws = Draw.query.filter_by(status='completed').count()
        total_winners = Winner.query.filter(Winner.status != 'void').count()

        # Value of prizes won (prizes without a value, e.g. goods, are not counted)
        total_prizes = float(
            db.session.query(func.coalesce(func.sum(Prize.value), 0))
            .join(Winner, Winner.prize_id == Prize.id)
            .filter(Winner.status != 'void')
            .scalar()
        )

        return jsonify({
            'total_draws': total_draws,
            'completed_draws': completed_draws,
            'total_winners': total_winners,
            'total_prizes': total_prizes
        })
    except Exception as e:
        current_app.logger.error(f"Error getting stats: {e}")
        return jsonify({
            'total_draws': 0,
            'completed_draws': 0,
            'total_winners': 0,
            'total_prizes': 0
        })

# ---------------------------------------------------------------- draw rules & whitelist

def _rules_error(e):
    db.session.rollback()
    return jsonify({'success': False, 'message': str(e)}), 400


@admin_bp.route('/admin/draws/<int:draw_id>/rules', methods=['PATCH'])
@login_required
@admin_required
@audit_log('Update draw rules')
def update_draw_rules(draw_id):
    data = request.get_json(silent=True) or {}
    try:
        draw = whitelist_service.update_draw_rules(
            draw_id, entry_mode=data.get('entry_mode'), whitelist_enabled=data.get('whitelist_enabled'))
    except ImportRejected as e:
        return _rules_error(e)
    return jsonify({'success': True, 'entry_mode': draw.entry_mode,
                    'whitelist_enabled': draw.whitelist_enabled})


@admin_bp.route('/admin/draws/<int:draw_id>/whitelist', methods=['GET'])
@login_required
@admin_required
def get_whitelist(draw_id):
    try:
        return jsonify({'success': True, **whitelist_service.whitelist_summary(draw_id)})
    except ImportRejected as e:
        return jsonify({'success': False, 'message': str(e)}), 404


@admin_bp.route('/admin/draws/<int:draw_id>/whitelist', methods=['POST'])
@login_required
@admin_required
@audit_log('Upload whitelist')
def upload_whitelist(draw_id):
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    try:
        result = whitelist_service.replace_whitelist(draw_id, secure_filename(file.filename), file.read())
    except ImportRejected as e:
        return _rules_error(e)
    return jsonify({'success': True, **result})


@admin_bp.route('/admin/draws/<int:draw_id>/whitelist', methods=['DELETE'])
@login_required
@admin_required
@audit_log('Remove whitelist')
def delete_whitelist(draw_id):
    try:
        return jsonify({'success': True, **whitelist_service.clear_whitelist(draw_id)})
    except ImportRejected as e:
        return _rules_error(e)
