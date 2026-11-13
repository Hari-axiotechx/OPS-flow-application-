class ApiError(Exception):
    """Raised for any expected/user-facing error. The route handler turns
    this into {"ok": false, "error": <message>}, exactly like the old
    Apps Script backend's try/catch did."""
    pass
