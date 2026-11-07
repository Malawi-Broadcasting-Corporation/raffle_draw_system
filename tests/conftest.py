import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Draw, Prize, User, WhitelistEntry
from app.utils.security import hash_password


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def make_draw(db):
    def _make(name='Test Draw', prizes=((('TV', 1),)), **kwargs):
        draw = Draw(name=name, **kwargs)
        draw.prizes = [Prize(name=n, quantity=q, draw_order=i) for i, (n, q) in enumerate(prizes)]
        db.session.add(draw)
        db.session.commit()
        return draw
    return _make


@pytest.fixture
def whitelist(db):
    def _add(draw, *phones):
        db.session.add_all(WhitelistEntry(draw_id=draw.id, phone_number=p) for p in phones)
        db.session.commit()
    return _add


@pytest.fixture
def ready():
    """Lock a draw, give it a manual seed and start it."""
    from app.services import draw_service

    def _ready(draw, seed='351624'):
        draw_service.lock_draw(draw.id)
        draw_service.seed_manually(draw.id, seed, 'Dice rolled on air (test)')
        draw_service.start_draw(draw.id)
    return _ready


@pytest.fixture
def client(app, db):
    db.session.add(User(username='admin', password_hash=hash_password('pw'), role='admin'))
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'pw'})
    return c
