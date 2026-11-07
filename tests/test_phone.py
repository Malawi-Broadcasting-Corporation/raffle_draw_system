import pytest

from app.utils.phone import PhoneError, mask_phone, normalize_phone


@pytest.mark.parametrize('raw', [
    '0999123456', '999123456', '265999123456', '+265999123456', '+265 999 123 456',
    '00265999123456', '0999-123-456', '(0999) 123456', '265999123456.0', 265999123456,
])
def test_accepted_formats_normalise_to_one_number(raw):
    assert normalize_phone(raw) == '265999123456'


@pytest.mark.parametrize('raw,code', [
    ('2.65999E+11', 'scientific_notation'),
    ('2.66e11', 'scientific_notation'),
    ('', 'empty'),
    (None, 'empty'),
    ('nan', 'empty'),
    ('0999abc456', 'invalid_characters'),
    ('12345', 'wrong_length'),
    ('0099123456', 'wrong_length'),
    ('27999123456', 'wrong_length'),
])
def test_rejected_values(raw, code):
    with pytest.raises(PhoneError) as e:
        normalize_phone(raw)
    assert e.value.code == code


def test_mask_shows_local_format():
    assert mask_phone('265999123456') == '0999***456'
