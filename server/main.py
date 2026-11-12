# Entry point for the web server: the core app plus the extra pages in extras.py.
from app import app
import extras

app.include_router(extras.router)
