from datetime import datetime

from app.extensions import db

DRAW_STATUSES = ('draft', 'active', 'paused', 'completed', 'cancelled')

# How entries are counted when the eligible pool is built (see issue #4).
ENTRY_PER_SMS = 'per_sms'        # every row is a separate chance
ENTRY_PER_NUMBER = 'per_number'  # repeats from one number count once
ENTRY_MODES = (ENTRY_PER_SMS, ENTRY_PER_NUMBER)


class Draw(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    currency = db.Column(db.String(10), default='MWK')
    status = db.Column(db.String(20), nullable=False, default='draft')
    entry_mode = db.Column(db.String(20), nullable=False, default=ENTRY_PER_SMS)
    whitelist_enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    scheduled_for = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # Checkable draws (issue #6). Set once when the entry list is locked.
    locked_at = db.Column(db.DateTime)
    pool_size = db.Column(db.Integer)
    pool_fingerprint = db.Column(db.String(64))   # SHA-256 hex of the locked eligible pool
    seed = db.Column(db.String(128))              # external randomness obtained after the lock
    seed_source = db.Column(db.String(50))        # e.g. 'drand', 'manual'
    seed_reference = db.Column(db.String(255))    # e.g. drand round number or who read it on air

    participants = db.relationship('Participant', backref='draw', lazy=True,
                                   cascade='all, delete-orphan')
    winners = db.relationship('Winner', backref='draw', lazy=True,
                              cascade='all, delete-orphan')
    prizes = db.relationship(
        'Prize', backref='draw', lazy=True,
        cascade='all, delete-orphan',
        order_by='[Prize.draw_order, Prize.id]',
    )

    @property
    def total_winners(self):
        return sum(p.quantity for p in self.prizes)

    @property
    def is_locked(self):
        return self.locked_at is not None


class Prize(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    draw_id = db.Column(db.Integer, db.ForeignKey('draw.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)         # "55-inch TV", "MWK 50,000 cash"
    prize_type = db.Column(db.String(20), default='goods')    # cash, goods, voucher, service
    description = db.Column(db.Text)
    value = db.Column(db.Numeric(14, 2))                      # optional, for reporting only
    currency = db.Column(db.String(10), default='MWK')
    quantity = db.Column(db.Integer, nullable=False, default=1)
    draw_order = db.Column(db.Integer, default=0)             # lower number is drawn first
    image_path = db.Column(db.String(255))
