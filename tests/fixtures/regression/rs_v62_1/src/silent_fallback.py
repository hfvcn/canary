def read_flag() -> bool:
    try:
        run_step()
    except Exception:
        return False
    return True
