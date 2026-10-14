import secrets


def new_pad_token():
    return secrets.token_urlsafe(32)
