ENABLE_DBG_PRINT = True
def dbg_print(origin, *args, **kwargs):
    if ENABLE_DBG_PRINT:
        print(f"[{origin}]", *args, **kwargs)