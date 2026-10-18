import contextlib
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))


def run_main(main, argv):
    """Run a tool's main(argv); return (exit_code, stdout)."""
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            main(argv)
        except SystemExit as e:
            if isinstance(e.code, str):
                buf.write(e.code)
                code = 1
            else:
                code = e.code or 0
    return code, buf.getvalue().strip()
