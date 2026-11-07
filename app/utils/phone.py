def mask_phone(phone):
    """0999123456 -> 0999***456. Used for anything shown publicly."""
    phone = str(phone)
    if len(phone) <= 6:
        return phone
    return f"{phone[:4]}***{phone[-3:]}"