# app/utils/security.py
import hashlib
import secrets
from functools import wraps
from flask import request, jsonify, current_app
from flask_login import current_user
from app.models import AuditLog, db
from flask import make_response
import json

SENSITIVE_KEYS = {'password', 'api_key', 'token', 'secret'}

def hash_password(password):
    """Hash a password for storing."""
    salt = secrets.token_hex(16)
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    pwdhash = pwdhash.hex()
    return f"{salt}${pwdhash}"

def verify_password(stored_password, provided_password):
    """Verify a stored password against one provided by user"""
    salt, stored_hash = stored_password.split('$')
    pwdhash = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt.encode('utf-8'), 100000)
    pwdhash = pwdhash.hex()
    return pwdhash == stored_hash

def _redact(data):
    if isinstance(data, dict):
        return {k: '***' if str(k).lower() in SENSITIVE_KEYS else _redact(v)
                for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(i) for i in data]
    return data

def audit_log(action):
    """Decorator to log user actions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Execute the function first
            result = f(*args, **kwargs)
            
            # Log the action
            try:
                log_details = {
                    'endpoint': request.endpoint,
                    'method': request.method,
                    'args': dict(request.args)
                }
                
                # Add form data if present
                if request.form:
                    log_details['form'] = _redact(dict(request.form))
                
                # Add JSON data if present
                json_data = request.get_json(silent=True)
                if json_data:
                    log_details['json'] = _redact(json_data)

                resp = make_response(result)
                body = resp.get_json(silent=True) or {}
                log_details['status_code'] = resp.status_code
                log_details['success'] = body.get('success', resp.status_code < 400)
                
                log = AuditLog(
                    user_id=current_user.id if current_user.is_authenticated else None,
                    action=action,
                    details=json.dumps(log_details),
                    ip_address=request.remote_addr
                )
                db.session.add(log)
                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Failed to create audit log: {e}")
            
            return result
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def generate_api_key():
    """Generate a secure API key"""
    return secrets.token_urlsafe(32)