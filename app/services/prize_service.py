from decimal import Decimal

from app.models import Prize

VALID_TYPES = {'cash', 'goods', 'voucher', 'service'}


def summarize_prizes(prizes):
    """Short one-line description for lists, e.g. '1× 55-inch TV, 3× MWK 50,000'."""
    if not prizes:
        return 'No prizes yet'
    return ', '.join(f"{p.quantity}× {p.name}" for p in prizes)


def parse_prizes(raw):
    """Validate a list of prize dicts from a request and return Prize objects."""
    if not raw or not isinstance(raw, list):
        raise ValueError("At least one prize is required")

    prizes = []
    for i, item in enumerate(raw, start=1):
        name = (item.get('name') or '').strip()
        if not name:
            raise ValueError(f"Prize {i}: name is required")

        try:
            quantity = int(item.get('quantity', 1))
        except (TypeError, ValueError):
            raise ValueError(f"Prize {i}: quantity must be a whole number")
        if quantity < 1:
            raise ValueError(f"Prize {i}: quantity must be at least 1")

        prize_type = item.get('prize_type', 'goods')
        if prize_type not in VALID_TYPES:
            raise ValueError(f"Prize {i}: type must be one of {', '.join(sorted(VALID_TYPES))}")

        raw_value = item.get('value')
        try:
            value = Decimal(str(raw_value)) if raw_value not in (None, '') else None
        except ArithmeticError:
            raise ValueError(f"Prize {i}: value must be a number")

        prizes.append(Prize(
            name=name,
            prize_type=prize_type,
            description=item.get('description', ''),
            value=value,
            currency=item.get('currency', 'MWK'),
            quantity=quantity,
            draw_order=int(item.get('draw_order', i - 1)),
            image_path=item.get('image_path'),
        ))
    return prizes