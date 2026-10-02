"""Quick syntax check for all sibling cell .py files."""
import ast
from pathlib import Path

here = Path(__file__).parent
errors = []
for p in sorted(here.glob('*.py')):
    if p.name.startswith('_validate'):
        continue
    try:
        ast.parse(p.read_text(encoding='utf-8'))
        print(f'OK  {p.name}')
    except SyntaxError as e:
        errors.append((p.name, e))
        print(f'FAIL {p.name}: {e}')

if errors:
    raise SystemExit(f'{len(errors)} file(s) có syntax error')
print(f'\nAll {len(list(here.glob("*.py"))) - 1} cells OK')
