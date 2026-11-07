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
