import re

# A number Excel has turned into scientific notation, e.g. "2.65999E+11".
# The digits it dropped are gone for good, so the value must never be imported.
_SCIENTIFIC = re.compile(r'^[+-]?\d+(\.\d+)?[eE][+-]?\d+$')
# A whole number Excel/pandas wrote as a float, e.g. "265999123456.0"
_FLOAT_INT = re.compile(r'^(\d+)\.0+$')
_SEPARATORS = re.compile(r'[\s\-().]')


class PhoneError(ValueError):
    """Why a value isn't a usable Malawi phone number. `code` is stored/reported."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def is_scientific(value):
    return bool(_SCIENTIFIC.match(str(value).strip()))


def normalize_phone(value):
    """Return a Malawi number in international form without '+', e.g. '265999123456'.

    Accepts 0999123456, 999123456, 265999123456, +265 999 123 456, 00265999123456.
    Raises PhoneError for anything else.
    """
    raw = '' if value is None else str(value).strip()
    if not raw or raw.lower() in ('nan', 'none', 'null'):
        raise PhoneError('empty', 'Phone number is empty')
    if is_scientific(raw):
        raise PhoneError('scientific_notation',
                         f"'{raw}' is in scientific notation; digits have been lost")

    m = _FLOAT_INT.match(raw)
    if m:
        raw = m.group(1)

    digits = _SEPARATORS.sub('', raw)
    if digits.startswith('+'):
        digits = digits[1:]
    elif digits.startswith('00'):
        digits = digits[2:]
    if not digits.isdigit():
        raise PhoneError('invalid_characters', f"'{raw}' contains characters that aren't digits")

    if len(digits) == 12 and digits.startswith('265'):
        national = digits[3:]
    elif len(digits) == 10 and digits.startswith('0'):
        national = digits[1:]
    elif len(digits) == 9:
        national = digits
    else:
        raise PhoneError('wrong_length', f"'{raw}' is not a Malawi phone number")

    if national[0] == '0':
        raise PhoneError('wrong_length', f"'{raw}' is not a Malawi phone number")
    return '265' + national


def to_local(phone):
    """265999123456 -> 0999123456 (how Malawians read their own number)."""
    phone = str(phone)
    if phone.startswith('265') and len(phone) == 12:
        return '0' + phone[3:]
    return phone


def mask_phone(phone):
    """265999123456 -> 0999***456. Used for anything shown publicly."""
    phone = to_local(phone)
    if len(phone) <= 6:
        return phone
    return f"{phone[:4]}***{phone[-3:]}"
