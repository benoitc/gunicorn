from importlib import import_module

def define_env(env):
    """Register template variables for MkDocs macros."""
    gunicorn = import_module("gunicorn")
    env.variables.update(
        release=gunicorn.__version__,
        version=gunicorn.__version__,
        github_repo="https://github.com/benoitc/gunicorn",
        pypi_url=f"https://pypi.org/project/gunicorn/{gunicorn.__version__}/",
    )
