import os


# Configuration is validated while application modules are imported.
os.environ.setdefault(
    "SECRET_KEY",
    "test-only-secret-key-with-at-least-32-characters",
)

