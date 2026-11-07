from datetime import datetime

from app.extensions import db


class Participant(db.Model):
    """One entry into a draw. With per-SMS draws a phone number can have many rows."""
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)   # normalised, e.g. 265999123456
    name = db.Column(db.String(150))
    source = db.Column(db.String(20), default='manual')       # manual, upload, api
    batch_id = db.Column(db.Integer, db.ForeignKey('import_batch.id'))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_verified = db.Column(db.Boolean, nullable=False, default=True)
    # Why the entry can't win, e.g. 'not_on_whitelist'. NULL means eligible.
    excluded_reason = db.Column(db.String(50))

    __table_args__ = (
        db.Index('ix_participant_draw_phone', 'draw_id', 'phone_number'),
    )


class ImportBatch(db.Model):
    """One file upload or API poll. Lets us refuse the same file twice and audit every import."""
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    source = db.Column(db.String(20), nullable=False)         # upload, api
    filename = db.Column(db.String(255))
    file_sha256 = db.Column(db.String(64))                    # NULL for API polls
    rows_total = db.Column(db.Integer, default=0)
    rows_accepted = db.Column(db.Integer, default=0)
    rows_rejected = db.Column(db.Integer, default=0)
    rows_excluded = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    entries = db.relationship('Participant', backref='batch', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('draw_id', 'file_sha256', name='uq_import_batch_draw_file'),
    )


class WhitelistEntry(db.Model):
    """A number allowed to win a whitelisted draw."""
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(150))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('draw_id', 'phone_number', name='uq_whitelist_draw_phone'),
    )
