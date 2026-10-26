"""Keep the dependency executable in the deployed Python function bundle."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
candidate = root / '.vercel/python/.venv/bin/deno'
if not candidate.is_file():
    import deno
    candidate = Path(deno.find_deno_bin())
destination = root / 'runtime/deno'
destination.parent.mkdir(exist_ok=True)
shutil.copy2(candidate, destination)
destination.chmod(0o755)
print('Bundled JavaScript runtime.')
