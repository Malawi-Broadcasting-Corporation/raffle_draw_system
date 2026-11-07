from collections import Counter
from datetime import datetime, timezone

import pytest

from app.models import Participant, Winner
from app.services import checkable, draw_service
from app.services.draw_service import DrawError
from app.services.import_service import import_file

ENTRIES = b"phone\n" + b"".join(f"0999{i:06d}\n".encode() for i in range(1, 21))


def _draw_all(draw_id, n):
    return [draw_service.draw_next_winner(draw_id) for _ in range(n)]


# ---------------------------------------------------------------- pure algorithm

def test_fingerprint_changes_with_any_change():
    pool = [(1, '265999000001'), (2, '265999000002')]
    fp = checkable.fingerprint(pool)
    assert fp == checkable.fingerprint(list(pool))
    assert fp != checkable.fingerprint([(1, '265999000001'), (2, '265999000003')])
    assert fp != checkable.fingerprint(pool[::-1])
    assert fp != checkable.fingerprint(pool[:1])


def test_pick_index_is_deterministic_and_in_range():
    key = checkable.draw_key('f' * 64, 'seed')
    assert [checkable.pick_index(key, n, 7) for n in range(1, 50)] == \
           [checkable.pick_index(key, n, 7) for n in range(1, 50)]
    assert all(0 <= checkable.pick_index(key, n, 7) < 7 for n in range(1, 500))
    assert checkable.pick_index(key, 1, 1) == 0


def test_pick_index_is_roughly_uniform():
    key = checkable.draw_key('a' * 64, 'uniformity')
    counts = Counter(checkable.pick_index(key, n, 5) for n in range(1, 10001))
    assert all(1800 < c < 2200 for c in counts.values()), counts


def test_different_seed_gives_different_order():
    pool = [(i, f'265999{i:06d}') for i in range(100)]
    fp = checkable.fingerprint(pool)
    a = [checkable.pick(checkable.draw_key(fp, 'seed-a'), n, pool, set())[0] for n in range(1, 6)]
    b = [checkable.pick(checkable.draw_key(fp, 'seed-b'), n, pool, set())[0] for n in range(1, 6)]
    assert a != b


def test_manual_seed_rules():
    with pytest.raises(checkable.SeedError):
        checkable.validate_manual_seed('123', 'dice')
    with pytest.raises(checkable.SeedError):
        checkable.validate_manual_seed('351624', '')
    assert checkable.validate_manual_seed(' 351624 ', ' dice ') == ('351624', 'dice')


# ---------------------------------------------------------------- drand

INFO = {'genesis_time': 1_000_000, 'period': 30, 'hash': 'abc'}


def test_drand_round_is_strictly_after_lock():
    for offset in (0, 1, 29, 30, 31):
        lock_ts = INFO['genesis_time'] + 100 * 30 + offset
        locked_at = datetime.fromtimestamp(lock_ts, timezone.utc).replace(tzinfo=None)
        round_no, round_time = checkable.drand_round_after(locked_at, INFO)
        assert round_time > lock_ts
        assert round_time - lock_ts <= 30


def test_fetch_drand_waits_for_the_round_after_lock():
    lock_ts = INFO['genesis_time'] + 100 * 30 + 10          # round 101's time is +0, so round 102
    clock = {'now': lock_ts + 1}
    requested = []

    def get_json(url):
        requested.append(url)
        if url.endswith('/info'):
            return INFO
        rnd = int(url.rsplit('/', 1)[1])
        return {'round': rnd, 'randomness': f'rand-{rnd}'}

    def sleep(s):
        clock['now'] += s

    locked_at = datetime.fromtimestamp(lock_ts, timezone.utc).replace(tzinfo=None)
    value, ref = checkable.fetch_drand_seed(locked_at, get_json=get_json, sleep=sleep,
                                            now=lambda: clock['now'])
    assert value == 'rand-102'
    assert 'round 102' in ref
    assert clock['now'] >= INFO['genesis_time'] + 101 * 30   # waited until the round existed


def test_fetch_drand_unreachable_suggests_manual():
    with pytest.raises(checkable.SeedError, match='manual'):
        checkable.fetch_drand_seed(datetime.utcnow(), get_json=lambda url: None)


# ---------------------------------------------------------------- full flow

def test_lock_seed_start_draw_replay(make_draw, ready):
    draw = make_draw(prizes=(('TV', 1), ('Cash', 3)))
    import_file(draw.id, 'e.csv', ENTRIES)
    ready(draw)
    assert draw.pool_size == 20 and len(draw.pool_fingerprint) == 64

    winners = _draw_all(draw.id, 4)
    assert len({w['phone_number'] for w in winners}) == 4
    assert draw_service.get_state(draw.id)['status'] == 'completed'

    result = draw_service.replay_draw(draw.id)
    assert result['fingerprint_ok']
    assert [ok for *_, ok in result['picks']] == [True] * 4


def test_algorithm_golden_values():
    """Pinned results for a fixed pool and seed.

    If this test fails, the selection algorithm changed and past draws would no longer replay.
    Never update these values; add a new ALGORITHM_VERSION instead.
    """
    pool = [(i, f'265999{i:06d}') for i in range(1, 21)]
    fp = checkable.fingerprint(pool)
    assert fp == '6fce6c84fa7b782b32cc9fbfe263b7a1c65a3ca406016473a99e44932093ac68'
    key, won, picks = checkable.draw_key(fp, '351624'), set(), []
    for n in range(1, 6):
        entry_id, phone = checkable.pick(key, n, pool, won)
        won.add(phone)
        picks.append(entry_id)
    assert picks == [12, 10, 19, 7, 17]


def test_cannot_start_without_lock_and_seed(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    with pytest.raises(DrawError, match='Lock'):
        draw_service.start_draw(draw.id)
    draw_service.lock_draw(draw.id)
    with pytest.raises(DrawError, match='seed'):
        draw_service.start_draw(draw.id)


def test_seed_needs_lock_and_can_never_change(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    with pytest.raises(DrawError, match='Lock'):
        draw_service.seed_manually(draw.id, '351624', 'dice')
    draw_service.lock_draw(draw.id)
    draw_service.seed_manually(draw.id, '351624', 'dice')
    with pytest.raises(DrawError, match='never be changed'):
        draw_service.seed_manually(draw.id, '999999', 'dice again')
    with pytest.raises(DrawError, match='never be changed'):
        draw_service.seed_from_drand(draw.id, fetch=lambda t: ('x', 'y'))


def test_unlock_only_before_seed(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    draw_service.lock_draw(draw.id)
    draw_service.unlock_draw(draw.id)
    assert not draw.is_locked
    draw_service.lock_draw(draw.id)
    draw_service.seed_manually(draw.id, '351624', 'dice')
    with pytest.raises(DrawError, match='no longer be unlocked'):
        draw_service.unlock_draw(draw.id)


def test_drand_seed_is_recorded(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    draw_service.lock_draw(draw.id)
    seen = {}

    def fake_fetch(locked_at):
        seen['locked_at'] = locked_at
        return 'abc123' * 10, 'drand round 42'

    state = draw_service.seed_from_drand(draw.id, fetch=fake_fetch)
    assert seen['locked_at'] == draw.locked_at
    assert state['seed_source'] == 'drand' and state['seed_reference'] == 'drand round 42'
    assert 'seed' not in state  # never exposed on public endpoints


def test_void_and_redraw_still_replays(make_draw, ready):
    draw = make_draw(prizes=(('TV', 2),))
    import_file(draw.id, 'e.csv', ENTRIES)
    ready(draw)
    first = draw_service.draw_next_winner(draw.id)
    w = Winner.query.filter_by(draw_id=draw.id, position=1).one()
    draw_service.void_winner(w.id, 'no_answer')
    redraw = draw_service.draw_next_winner(draw.id)
    assert redraw['position'] == 2 and redraw['prize']['name'] == 'TV'
    assert redraw['phone_number'] != first['phone_number']
    draw_service.draw_next_winner(draw.id)
    assert all(ok for *_, ok in draw_service.replay_draw(draw.id)['picks'])


def test_tampering_is_detected(make_draw, ready, db):
    draw = make_draw(prizes=(('TV', 2),))
    import_file(draw.id, 'e.csv', ENTRIES)
    ready(draw)
    draw_service.draw_next_winner(draw.id)

    sneaky = Participant.query.filter_by(draw_id=draw.id).order_by(Participant.id.desc()).first()
    sneaky.phone_number = '265888777666'
    db.session.commit()

    with pytest.raises(DrawError, match='changed since it was locked'):
        draw_service.draw_next_winner(draw.id)
    assert not draw_service.replay_draw(draw.id)['fingerprint_ok']


def test_late_api_entries_do_not_change_the_pool(make_draw, ready):
    from app.services.import_service import import_entries, rows_from_json
    draw = make_draw(prizes=(('TV', 2),))
    import_file(draw.id, 'e.csv', ENTRIES)
    ready(draw)
    import_entries(draw.id, rows_from_json(['0888000001']), source='api')
    draw_service.draw_next_winner(draw.id)  # fingerprint still matches
    assert draw_service.replay_draw(draw.id)['fingerprint_ok']


def test_locked_entries_cannot_be_deleted_or_verified(client, make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    draw_service.lock_draw(draw.id)
    entry = Participant.query.filter_by(draw_id=draw.id).first()
    assert client.delete(f'/api/participants/delete/{entry.id}').status_code == 409
    assert client.post('/api/participants/bulk-verify',
                       json={'participant_ids': [entry.id]}).status_code == 409


def test_http_flow_and_cli_replay(app, client, make_draw):
    draw = make_draw(prizes=(('TV', 1),))
    import_file(draw.id, 'e.csv', ENTRIES)
    assert client.post(f'/api/draws/{draw.id}/lock').get_json()['state']['locked']
    r = client.post(f'/api/draws/{draw.id}/seed/manual', json={'seed': '351624', 'reference': 'dice'})
    assert r.get_json()['state']['seeded']
    assert client.post(f'/api/draws/{draw.id}/start').get_json()['success']
    assert client.post(f'/api/draws/{draw.id}/draw-winner').get_json()['success']
    replay = client.get(f'/api/draws/{draw.id}/replay').get_json()['replay']
    assert replay['all_ok']

    result = app.test_cli_runner().invoke(args=['replay-draw', str(draw.id)])
    assert result.exit_code == 0, result.output
    assert 'Replay matches' in result.output
