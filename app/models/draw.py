from datetime import datetime
from app import db


class Draw(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    currency = db.Column(db.String(10), default='MWK')
    # DEPRECATED: replaced by Prize rows. Kept until templates are updated, then dropped.
    prize_amount = db.Column(db.Float, nullable=True)
    number_of_winners = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='draft')  # draft, active, paused, completed, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    scheduled_for = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    participants = db.relationship('Participant', backref='draw', lazy=True)
    winners = db.relationship('Winner', backref='draw', lazy=True)
    prizes = db.relationship(
        'Prize', backref='draw', lazy=True,
        cascade='all, delete-orphan',
        order_by='[Prize.draw_order, Prize.id]',
    )

    @property
    def total_winners(self):
        return sum(p.quantity for p in self.prizes)


class Prize(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)         # "55-inch TV", "MWK 50,000 cash", "50kg fertilizer"
    prize_type = db.Column(db.String(20), default='goods')    # cash, goods, voucher, service
    description = db.Column(db.Text)
    value = db.Column(db.Numeric(14, 2))                      # optional, for reporting only
    currency = db.Column(db.String(10), default='MWK')
    quantity = db.Column(db.Integer, nullable=False, default=1)
    draw_order = db.Column(db.Integer, default=0)             # lower number is drawn first
    image_path = db.Column(db.String(255))