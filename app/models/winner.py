from datetime import datetime
from app import db


class Winner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    prize_id = db.Column(db.Integer, db.ForeignKey('prize.id'), nullable=False)
    position = db.Column(db.Integer)                          # overall order within the draw
    status = db.Column(db.String(20), nullable=False, default='drawn')  # drawn, contacted, claimed, void
    won_at = db.Column(db.DateTime, default=datetime.utcnow)

    participant = db.relationship('Participant', backref='wins')
    prize = db.relationship('Prize', backref='winners')

    __table_args__ = (
        db.UniqueConstraint('draw_id', 'participant_id', name='uq_winner_draw_participant'),
        db.UniqueConstraint('draw_id', 'position', name='uq_winner_draw_position'),
    )