from datetime import datetime

from app.extensions import db

WINNER_STATUSES = ('drawn', 'confirmed', 'void')


class Winner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    prize_id = db.Column(db.Integer, db.ForeignKey('prize.id'), nullable=False)
    # Overall order within the draw (1, 2, 3...). Voided winners keep their position,
    # so a redraw is simply the next position. Checkable draws derive pick n from it.
    position = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='drawn')
    void_reason = db.Column(db.String(50))     # no_answer, ineligible, ...
    won_at = db.Column(db.DateTime, default=datetime.utcnow)
    status_changed_at = db.Column(db.DateTime)

    participant = db.relationship('Participant', backref='wins')
    prize = db.relationship('Prize', backref='winners')

    __table_args__ = (
        db.UniqueConstraint('draw_id', 'participant_id', name='uq_winner_draw_participant'),
        db.UniqueConstraint('draw_id', 'position', name='uq_winner_draw_position'),
    )
