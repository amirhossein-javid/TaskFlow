def is_email_conflict(error):
    """Recognize only the PostgreSQL constraints protecting email identity."""
    diagnostic = getattr(error.__cause__, "diag", None)
    return getattr(diagnostic, "constraint_name", None) in {
        "accounts_user_email_key",
        "unique_user_email_ci",
    }
