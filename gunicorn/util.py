
def import_app(module):
    parts = module.rsplit(":", 1)
    if len(parts) == 1:
        module, obj = module, "application"
    else:
        module, obj = parts[0], parts[1]
    mod = __import__(module)
    parts = module.split(".")
    for p in parts[1:]:
        mod = getattr(mod, p, None)
        if mod is None:
            raise ImportError("Failed to import: %s" % module)
    app = getattr(mod, obj, None)
    if app is None:
        raise ImportError("Failed to find application object: %r" % obj)
    if not callable(app):
        raise TypeError("Application object must be callable.")
    return app
    