from datetime import datetime

from app.extensions import db


class APIConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    endpoint_url = db.Column(db.String(500))
    auth_method = db.Column(db.String(20), default='none')
    api_key = db.Column(db.String(200))
    refresh_interval = db.Column(db.Integer, default=1)  # minutes
    is_active = db.Column(db.Boolean, default=False)
    last_sync = db.Column(db.DateTime)
    default_draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=True)


class APIResponseLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_config_id = db.Column(db.Integer, db.ForeignKey('api_config.id'), nullable=False)
    request_url = db.Column(db.String(500), nullable=False)
    request_method = db.Column(db.String(10), nullable=False, default='GET')
    response_status = db.Column(db.Integer)
    response_headers = db.Column(db.Text)
    response_body = db.Column(db.Text)
    error_message = db.Column(db.Text)
    participants_added = db.Column(db.Integer, default=0)
    success = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    api_config = db.relationship('APIConfig', backref=db.backref('response_logs', lazy=True))
