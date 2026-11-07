# app/routes/participants.py
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import json
from app.extensions import db
from app.models import Participant, Draw, APIConfig, APIResponseLog
from app.services import import_service
from app.services.import_service import ImportRejected
from app.utils.security import audit_log, admin_required
from app.utils.api_service import api_service
import requests
from flask import current_app

participants_bp = Blueprint('participants', __name__)

@participants_bp.route('/participants')
@login_required
def manage_participants():
    draws = Draw.query.all()
    api_config = APIConfig.query.first()
    # Get recent API response logs (last 50)
    api_response_logs = APIResponseLog.query.order_by(APIResponseLog.timestamp.desc()).limit(50).all()
    
    return render_template('participants.html', 
                         draws=draws, 
                         api_config=api_config,
                         api_response_logs=api_response_logs)

@participants_bp.route('/api/participants/upload', methods=['POST'])
@login_required
@audit_log('Upload participants')
def upload_participants():
    file = request.files.get('file')
    draw_id = request.form.get('draw_id', type=int)
    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    if not draw_id:
        return jsonify({'success': False, 'message': 'No draw selected'}), 400

    try:
        summary = import_service.import_file(
            draw_id, secure_filename(file.filename), file.read(), user_id=current_user.id)
    except ImportRejected as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'message': summary.message(), 'summary': summary.to_dict()})

@participants_bp.route('/api/participants/<int:draw_id>')
@login_required
def get_participants(draw_id):
    participants = Participant.query.filter_by(draw_id=draw_id).join(Draw).all()
    return jsonify([{
        'id': p.id,
        'phone_number': p.phone_number,
        'name': p.name,
        'excluded_reason': p.excluded_reason,
        'batch_id': p.batch_id,
        'source': p.source,
        'added_at': p.added_at.isoformat() if p.added_at else None,
        'is_verified': p.is_verified,
        'draw_name': p.draw.name if p.draw else 'Unknown'
    } for p in participants])

@participants_bp.route('/api/participants/count/<int:draw_id>')
def get_participant_count(draw_id):
    count = Participant.query.filter_by(draw_id=draw_id, is_verified=True, excluded_reason=None).count()
    return jsonify({'count': count})

@participants_bp.route('/api/api-config', methods=['POST'])
@login_required
@admin_required
@audit_log('Update API configuration')
def update_api_config():
    data = request.get_json()
    
    api_config = APIConfig.query.first()
    if not api_config:
        api_config = APIConfig()
        db.session.add(api_config)
    
    api_config.endpoint_url = data.get('endpoint_url')
    api_config.auth_method = data.get('auth_method', 'none')
    api_config.api_key = data.get('api_key')
    api_config.refresh_interval = data.get('refresh_interval', 5)
    api_config.is_active = data.get('is_active', False)
    api_config.default_draw_id = data.get('default_draw_id')  
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'API configuration updated'})

@participants_bp.route('/api/api-config/status', methods=['GET'])
@login_required
def get_api_status():
    """Get current API service status"""
    return jsonify({
        'is_running': api_service.is_running,
        'is_active': api_service.is_running
    })

@participants_bp.route('/api/api-config/start', methods=['POST'])
@login_required
@admin_required
@audit_log('Start API service')
def start_api_service():
    """Start the API polling service"""
    try:
        success = api_service.start_polling()
        if success:
            return jsonify({'success': True, 'message': 'API service started'})
        else:
            return jsonify({'success': False, 'message': 'API service is already running'})
    except Exception as e:
        current_app.logger.error(f"Error starting API service: {e}")
        return jsonify({'success': False, 'message': f'Error starting API service: {str(e)}'})

@participants_bp.route('/api/api-config/stop', methods=['POST'])
@login_required
@admin_required
@audit_log('Stop API service')
def stop_api_service():
    """Stop the API polling service"""
    try:
        api_service.stop_polling()
        return jsonify({'success': True, 'message': 'API service stopped'})
    except Exception as e:
        current_app.logger.error(f"Error stopping API service: {e}")
        return jsonify({'success': False, 'message': f'Error stopping API service: {str(e)}'})

@participants_bp.route('/api/api-config/test', methods=['POST'])
@login_required
@admin_required
@audit_log('Test API connection')
def test_api_connection():
    """Test the API connection"""
    try:
        api_config = APIConfig.query.first()
        if not api_config or not api_config.endpoint_url:
            return jsonify({'success': False, 'message': 'No API endpoint configured'})
        
        headers = {}
        if api_config.auth_method == 'api_key' and api_config.api_key:
            headers['Authorization'] = f'Bearer {api_config.api_key}'
        elif api_config.auth_method == 'basic_auth' and api_config.api_key:
            headers['Authorization'] = f'Basic {api_config.api_key}'
        
        response = requests.get(api_config.endpoint_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return jsonify({
                'success': True, 
                'message': f'API connection successful. Status: {response.status_code}'
            })
        else:
            return jsonify({
                'success': False, 
                'message': f'API returned status code: {response.status_code}'
            })
            
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'API connection failed: {str(e)}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error testing API: {str(e)}'})

@participants_bp.route('/api/response-logs')
@login_required
def get_response_logs():
    """Get API response logs"""
    logs = APIResponseLog.query.order_by(APIResponseLog.timestamp.desc()).limit(50).all()
    return jsonify([{
        'id': log.id,
        'timestamp': log.timestamp.isoformat() if log.timestamp else None,
        'request_url': log.request_url,
        'response_status': log.response_status,
        'participants_added': log.participants_added,
        'error_message': log.error_message,
        'success': log.success
    } for log in logs])

@participants_bp.route('/api/response-log/<int:log_id>')
@login_required
def get_response_log(log_id):
    """Get detailed API response log"""
    log = APIResponseLog.query.get_or_404(log_id)
    
    response_headers = None
    response_body = None
    
    try:
        if log.response_headers:
            response_headers = json.loads(log.response_headers)
    except:
        response_headers = log.response_headers
    
    try:
        if log.response_body:
            response_body = json.loads(log.response_body)
    except:
        response_body = log.response_body
    
    return jsonify({
        'id': log.id,
        'timestamp': log.timestamp.isoformat() if log.timestamp else None,
        'request_url': log.request_url,
        'request_method': log.request_method,
        'response_status': log.response_status,
        'response_headers': response_headers,
        'response_body': response_body,
        'error_message': log.error_message,
        'participants_added': log.participants_added,
        'success': log.success
    })

@participants_bp.route('/api/response-logs/clear', methods=['POST'])
@login_required
@admin_required
@audit_log('Clear API response logs')
def clear_response_logs():
    """Clear all API response logs"""
    try:
        # Delete all logs
        num_deleted = db.session.query(APIResponseLog).delete()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Cleared {num_deleted} API response logs'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing response logs: {e}")
        return jsonify({
            'success': False, 
            'message': f'Error clearing response logs: {str(e)}'
        })

@participants_bp.route('/api/participants/stats')
@login_required
def get_participants_stats():
    """Get participants statistics"""
    try:
        total_participants = Participant.query.count()
        verified_participants = Participant.query.filter_by(is_verified=True).count()
        api_participants = Participant.query.filter_by(source='api').count()
        manual_participants = Participant.query.filter_by(source='manual').count()
        
        # Participants per draw
        draws = Draw.query.all()
        draw_stats = []
        for draw in draws:
            count = Participant.query.filter_by(draw_id=draw.id).count()
            verified_count = Participant.query.filter_by(draw_id=draw.id, is_verified=True).count()
            draw_stats.append({
                'draw_name': draw.name,
                'total_participants': count,
                'verified_participants': verified_count
            })
        
        return jsonify({
            'success': True,
            'stats': {
                'total_participants': total_participants,
                'verified_participants': verified_participants,
                'pending_verification': total_participants - verified_participants,
                'api_participants': api_participants,
                'manual_participants': manual_participants,
                'draw_stats': draw_stats
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error getting participant stats: {e}")
        return jsonify({
            'success': False,
            'message': f'Error getting statistics: {str(e)}'
        })

@participants_bp.route('/api/participants/delete/<int:participant_id>', methods=['DELETE'])
@login_required
@admin_required
@audit_log('Delete participant')
def delete_participant(participant_id):
    """Delete a participant"""
    try:
        participant = Participant.query.get_or_404(participant_id)
        db.session.delete(participant)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Participant deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting participant: {e}")
        return jsonify({
            'success': False,
            'message': f'Error deleting participant: {str(e)}'
        })

@participants_bp.route('/api/participants/bulk-delete', methods=['POST'])
@login_required
@admin_required
@audit_log('Bulk delete participants')
def bulk_delete_participants():
    """Bulk delete participants"""
    try:
        data = request.get_json()
        participant_ids = data.get('participant_ids', [])
        
        if not participant_ids:
            return jsonify({
                'success': False,
                'message': 'No participants selected'
            })
        
        # Delete participants
        deleted_count = Participant.query.filter(Participant.id.in_(participant_ids)).delete()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} participants'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk deleting participants: {e}")
        return jsonify({
            'success': False,
            'message': f'Error deleting participants: {str(e)}'
        })

@participants_bp.route('/api/participants/verify/<int:participant_id>', methods=['POST'])
@login_required
@admin_required
@audit_log('Verify participant')
def verify_participant(participant_id):
    """Verify a participant"""
    try:
        participant = Participant.query.get_or_404(participant_id)
        participant.is_verified = True
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Participant verified successfully'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error verifying participant: {e}")
        return jsonify({
            'success': False,
            'message': f'Error verifying participant: {str(e)}'
        })

@participants_bp.route('/api/participants/bulk-verify', methods=['POST'])
@login_required
@admin_required
@audit_log('Bulk verify participants')
def bulk_verify_participants():
    """Bulk verify participants"""
    try:
        data = request.get_json()
        participant_ids = data.get('participant_ids', [])
        
        if not participant_ids:
            return jsonify({
                'success': False,
                'message': 'No participants selected'
            })
        
        # Verify participants
        updated_count = Participant.query.filter(
            Participant.id.in_(participant_ids)
        ).update({
            'is_verified': True
        }, synchronize_session=False)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully verified {updated_count} participants'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk verifying participants: {e}")
        return jsonify({
            'success': False,
            'message': f'Error verifying participants: {str(e)}'
        })