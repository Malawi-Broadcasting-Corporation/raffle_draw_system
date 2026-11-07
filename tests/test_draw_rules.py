import io

import pytest

from app.models import ENTRY_PER_NUMBER, Participant
from app.services import draw_service, whitelist_service
from app.services.draw_service import DrawError, build_pool
from app.services.import_service import (
    EXCLUDED_NOT_ON_WHITELIST, ImportRejected, import_file,
)

ENTRIES = b"phone\n0999000001\n0999000001\n0999000001\n0888000002\n"


def reasons(draw):
    return {p.phone_number: p.excluded_reason
            for p in Participant.query.filter_by(draw_id=draw.id)}


# ---------------------------------------------------------------- entry mode (#4)

def test_per_sms_gives_one_ticket_per_entry(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    assert len(build_pool(draw)) == 4


def test_per_number_gives_one_ticket_per_phone(make_draw):
    draw = make_draw(entry_mode=ENTRY_PER_NUMBER)
    import_file(draw.id, 'e.csv', ENTRIES)
    pool = build_pool(draw)
    assert [phone for _, phone in pool] == ['265888000002', '265999000001']


def test_pool_order_is_stable(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', b"phone\n0999000009\n0888000001\n0999000001\n")
    assert [phone for _, phone in build_pool(draw)] == ['265888000001', '265999000001', '265999000009']


def test_start_counts_numbers_not_tickets(make_draw, db):
    # 4 tickets but only 2 different numbers: 3 prizes can't all be won.
    draw = make_draw(prizes=(('TV', 3),))
    import_file(draw.id, 'e.csv', ENTRIES)
    with pytest.raises(DrawError, match='Not enough eligible numbers'):
        draw_service.start_draw(draw.id)


def test_number_with_many_tickets_wins_only_once(make_draw):
    draw = make_draw(prizes=(('TV', 2),))
    import_file(draw.id, 'e.csv', ENTRIES)
    draw_service.start_draw(draw.id)
    won = {draw_service.draw_next_winner(draw.id)['phone_number'] for _ in range(2)}
    assert won == {'265999000001', '265888000002'}


def test_entry_mode_can_change_before_lock(make_draw):
    draw = make_draw()
    whitelist_service.update_draw_rules(draw.id, entry_mode=ENTRY_PER_NUMBER)
    assert draw.entry_mode == ENTRY_PER_NUMBER
    with pytest.raises(ImportRejected):
        whitelist_service.update_draw_rules(draw.id, entry_mode='per_hour')


def test_rules_frozen_once_winners_exist(make_draw):
    draw = make_draw(prizes=(('TV', 1),))
    import_file(draw.id, 'e.csv', ENTRIES)
    draw_service.start_draw(draw.id)
    draw_service.draw_next_winner(draw.id)
    with pytest.raises(ImportRejected, match='locked'):
        whitelist_service.update_draw_rules(draw.id, entry_mode=ENTRY_PER_NUMBER)


# ---------------------------------------------------------------- whitelist (#5)

def test_whitelist_uploaded_after_entries_rechecks_them(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    result = whitelist_service.replace_whitelist(draw.id, 'w.csv', b"phone,name\n0888000002,Grace\n")
    assert draw.whitelist_enabled
    assert result['numbers'] == 1 and result['entries_excluded'] == 3
    assert reasons(draw) == {'265999000001': EXCLUDED_NOT_ON_WHITELIST, '265888000002': None}


def test_replacing_whitelist_readmits_entries(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    whitelist_service.replace_whitelist(draw.id, 'w.csv', b"0888000002\n")
    whitelist_service.replace_whitelist(draw.id, 'w2.csv', b"0999000001\n")
    assert reasons(draw) == {'265999000001': None, '265888000002': EXCLUDED_NOT_ON_WHITELIST}


def test_clearing_whitelist_makes_everyone_eligible(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    whitelist_service.replace_whitelist(draw.id, 'w.csv', b"0888000002\n")
    whitelist_service.clear_whitelist(draw.id)
    assert not draw.whitelist_enabled
    assert set(reasons(draw).values()) == {None}


def test_whitelist_never_readmits_late_entries(make_draw, db):
    draw = make_draw()
    import_file(draw.id, 'e.csv', b"0999000001\n")
    p = Participant.query.filter_by(draw_id=draw.id).first()
    p.excluded_reason = 'received_after_lock'
    db.session.commit()
    whitelist_service.replace_whitelist(draw.id, 'w.csv', b"0999000001\n")
    assert reasons(draw) == {'265999000001': 'received_after_lock'}


def test_mangled_whitelist_is_refused_and_nothing_changes(make_draw):
    draw = make_draw()
    import_file(draw.id, 'e.csv', ENTRIES)
    with pytest.raises(ImportRejected, match='scientific notation'):
        whitelist_service.replace_whitelist(
            draw.id, 'whitelist.csv',
            b"phone,name\n2.65999E+11,Mary Banda\n2.66E+11,Grace Phiri\n2.66E+11,Faith Mwale\n")
    assert not draw.whitelist_enabled
    assert set(reasons(draw).values()) == {None}


def test_whitelist_duplicates_and_bad_rows_reported(make_draw):
    draw = make_draw()
    result = whitelist_service.replace_whitelist(draw.id, 'w.csv', b"phone\n0999000001\n+265999000001\nxyz\n")
    assert (result['numbers'], result['duplicates'], result['rejected']) == (1, 1, 1)


def test_cannot_switch_on_whitelist_without_numbers(make_draw):
    draw = make_draw()
    with pytest.raises(ImportRejected, match='Upload a whitelist'):
        whitelist_service.update_draw_rules(draw.id, whitelist_enabled=True)


def test_whitelist_endpoints(client, make_draw):
    draw = make_draw()
    r = client.post(f'/admin/draws/{draw.id}/whitelist', data={
        'file': (io.BytesIO(b"phone\n0999000001\n0888000002\n"), 'w.csv')},
        content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['numbers'] == 2
    assert client.get(f'/admin/draws/{draw.id}/whitelist').get_json()['numbers'] == 2
    r = client.patch(f'/admin/draws/{draw.id}/rules', json={'entry_mode': 'per_number'})
    assert r.get_json()['entry_mode'] == 'per_number'
    assert client.delete(f'/admin/draws/{draw.id}/whitelist').get_json()['success']
