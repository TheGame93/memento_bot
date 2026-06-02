import warnings


def suppress_ptb_user_warning() -> bool:
    try:
        from telegram.warnings import PTBUserWarning
    except Exception:
        return False
    warnings.filterwarnings("ignore", category=PTBUserWarning)
    return True
