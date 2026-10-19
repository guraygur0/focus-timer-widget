"""Console-free entry point with bounded crash logging."""
from pathlib import Path
from logging.handlers import RotatingFileHandler
import logging
import runpy
import sys

ROOT = Path(__file__).resolve().parent
ENTRY = 'focus.pyw'

def record_error(kind, value, tb):
    logging.error("Unhandled application error", exc_info=(kind, value, tb))

if __name__ == '__main__':
    (ROOT/'state').mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT/'state'/'crash.log', maxBytes=131072, backupCount=1, encoding='utf-8')
    logging.basicConfig(handlers=[handler], level=logging.ERROR)
    sys.excepthook = record_error
    sys.argv = [str(ROOT/ENTRY)]
    try:
        runpy.run_path(str(ROOT/ENTRY), run_name='__main__')
    except Exception:
        logging.exception("Application startup failed")
        raise SystemExit(1)
