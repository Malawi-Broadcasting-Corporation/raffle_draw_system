import io
import json
from datetime import datetime

import pandas as pd
import pytest

from app.models import ImportBatch, Participant
from app.services.import_service import (
    EXCLUDED_AFTER_LOCK, EXCLUDED_NOT_ON_WHITELIST, ImportRejected, import_entries, import_file,
    rows_from_json,
)


def entries(draw):
    return Participant.query.filter_by(draw_id=draw.id).order_by(Participant.id).all()


def test_csv_with_header_and_names(make_draw):
    draw = make_draw()
    data = b"phone,name\n0999123456,Mary Banda\n+265 888 000 111,Grace Phiri\n"
    summary = import_file(draw.id, 'export.csv', data)
    assert (summary.accepted, summary.rejected) == (2, 0)
    rows = entries(draw)
    assert [r.phone_number for r in rows] == ['265999123456', '265888000111']
    assert rows[0].name == 'Mary Banda'
    assert rows[0].source == 'upload' and rows[0].batch_id == summary.batch_id


def test_csv_without_header(make_draw):
    draw = make_draw()
    summary = import_file(draw.id, 'list.csv', b"0999123456\n0888000111\n")
    assert summary.accepted == 2


def test_each_row_is_an_entry_including_repeats(make_draw):
    draw = make_draw()
    summary = import_file(draw.id, 'e.csv', b"phone\n0999123456\n0999123456\n0999123456\n")
    assert summary.accepted == 3
    assert len(entries(draw)) == 3


def test_invalid_rows_are_rejected_with_reasons_and_valid_rows_kept(make_draw):
    draw = make_draw()
    summary = import_file(draw.id, 'e.csv', b"phone\n0999123456\n12345\n\n0999abc456\n")
    assert (summary.accepted, summary.rejected) == (1, 2)
    assert {p['line'] for p in summary.problems} == {3, 4}


def test_scientific_notation_rejects_the_whole_file(make_draw):
    draw = make_draw()
    data = b"phone,name\n2.65999E+11,Mary Banda\n2.66E+11,Grace Phiri\n0999123456,Ok\n"
    with pytest.raises(ImportRejected, match='scientific notation'):
        import_file(draw.id, 'whitelist.csv', data)
    assert entries(draw) == []
    assert ImportBatch.query.count() == 0


def test_same_file_cannot_be_imported_twice(make_draw):
    draw = make_draw()
    data = b"phone\n0999123456\n"
    import_file(draw.id, 'a.csv', data)
    with pytest.raises(ImportRejected, match='already imported'):
        import_file(draw.id, 'renamed.csv', data)
    assert len(entries(draw)) == 1


def test_same_file_can_go_into_a_different_draw(make_draw):
    a, b = make_draw('A'), make_draw('B')
    data = b"phone\n0999123456\n"
    import_file(a.id, 'x.csv', data)
    import_file(b.id, 'x.csv', data)
    assert len(entries(a)) == len(entries(b)) == 1


def test_excel_numbers_keep_all_digits(make_draw):
    draw = make_draw()
    buf = io.BytesIO()
    pd.DataFrame({'phone': [265999123456, 999000111], 'name': ['A', 'B']}).to_excel(buf, index=False)
    summary = import_file(draw.id, 'e.xlsx', buf.getvalue())
    assert summary.accepted == 2
    assert [r.phone_number for r in entries(draw)] == ['265999123456', '265999000111']


def test_json_upload(make_draw):
    draw = make_draw()
    data = json.dumps({'data': [{'msisdn': '0999123456', 'name': 'A'}, {'phone': '0888000111'}]}).encode()
    assert import_file(draw.id, 'e.json', data).accepted == 2


def test_xls_is_refused_with_a_hint(make_draw):
    draw = make_draw()
    with pytest.raises(ImportRejected, match='save as .xlsx'):
        import_file(draw.id, 'old.xls', b'whatever')


def test_whitelist_marks_others_not_eligible(make_draw, whitelist):
    draw = make_draw(whitelist_enabled=True)
    whitelist(draw, '265999123456')
    summary = import_file(draw.id, 'e.csv', b"phone\n0999123456\n0888000111\n")
    assert (summary.accepted, summary.excluded) == (1, 1)
    reasons = {r.phone_number: r.excluded_reason for r in entries(draw)}
    assert reasons == {'265999123456': None, '265888000111': EXCLUDED_NOT_ON_WHITELIST}


def test_upload_after_lock_is_refused(make_draw, db):
    draw = make_draw()
    draw.locked_at = datetime.utcnow()
    db.session.commit()
    with pytest.raises(ImportRejected, match='locked'):
        import_file(draw.id, 'e.csv', b"phone\n0999123456\n")


def test_api_entries_after_lock_are_kept_but_not_eligible(make_draw, db):
    draw = make_draw()
    draw.locked_at = datetime.utcnow()
    db.session.commit()
    summary = import_entries(draw.id, rows_from_json(['0999123456']), source='api')
    assert (summary.accepted, summary.excluded) == (0, 1)
    assert entries(draw)[0].excluded_reason == EXCLUDED_AFTER_LOCK


def test_api_pull_rejects_only_bad_rows(make_draw):
    draw = make_draw()
    summary = import_entries(draw.id, rows_from_json(['2.65999E+11', '0999123456']), source='api')
    assert (summary.accepted, summary.rejected) == (1, 1)


def test_upload_endpoint_reports_summary(client, make_draw):
    draw = make_draw()
    r = client.post('/api/participants/upload', data={
        'draw_id': str(draw.id), 'file': (io.BytesIO(b"phone\n0999123456\nbad\n"), 'e.csv'),
    }, content_type='multipart/form-data')
    body = r.get_json()
    assert r.status_code == 200 and body['success']
    assert body['summary']['accepted'] == 1 and body['summary']['rejected'] == 1


def test_upload_endpoint_explains_scientific_notation(client, make_draw):
    draw = make_draw()
    r = client.post('/api/participants/upload', data={
        'draw_id': str(draw.id), 'file': (io.BytesIO(b"phone\n2.66E+11\n"), 'w.csv'),
    }, content_type='multipart/form-data')
    assert r.status_code == 400
    assert 'Text' in r.get_json()['message']
