# imghdr.py (simple fallback for environments where stdlib imghdr is removed)
def what(h, _=None):
    # return None so callers treat file as unknown image type
    return None
