# AGENTS.md

This file is the handoff note for developers and coding agents working on
this project after cloning the repository.

## Project Purpose

This project is a Feishu native bot and ORC/OCR calculator for processing
recycled paper order images. The source tree is the authoritative development
copy. Build outputs, runtime data, logs, secrets, and packaged executables
must stay outside Git commits.

## Directory Map

- `orc_calc/`: calculator, OCR adapters, templates, local web/API entry points.
- `orc_calc/core/`: protected business calculation logic, field normalization,
  template parsing, and money formulas.
- `orc_calc/ocr/`: local PaddleOCR and cloud PaddleOCR adapters.
- `feishu_bot/`: Feishu long-connection bot, message parsing, card sessions,
  and Feishu API client.
- `static/`: local browser UI for the calculator/API.
- `tests/`: regression tests for calculator, OCR routing, Feishu cards, and
  project protection rules.
- `docs/`: setup notes, handoff records, and protection documentation.
- `packaging/portable/`: scripts and templates for the Windows portable build.
- `config/`: non-secret example configuration and template definitions.

The parent project may also contain:

- `../app/`: Windows portable runtime output. Do not commit it.
- `../server-upload/`: server deployment copy/output. Do not treat it as the
  canonical source unless a task explicitly says so.

## Setup From A Fresh Clone

Use `git clone`, not `pip install`; this is not currently packaged as a Python
package with `pyproject.toml` or `setup.py`.

```powershell
cd feishuORC
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-feishu.txt
copy .env.example .env
```

Edit `.env` locally and fill in real credentials:

```text
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
PADDLEOCR_ACCESS_TOKEN=...
```

`PADDLEOCR_ACCESS_TOKEN` may be left empty when using local OCR fallback.

## Common Commands

Check Feishu bot configuration:

```powershell
python -m feishu_bot.main --check-config
```

Run the local web/API app:

```powershell
python orc-calc.py serve --host 127.0.0.1 --port 8765 --open
```

Run the Feishu bot:

```powershell
run_feishu_bot.bat
```

Run the protection regression checks:

```powershell
check_project_protection.bat
```

Run Python tests directly:

```powershell
python -m unittest discover -s tests
```

## Safety Rules

Never commit real secrets or runtime data:

- `.env`
- real `FEISHU_APP_ID`
- real `FEISHU_APP_SECRET`
- real `PADDLEOCR_ACCESS_TOKEN`
- `runtime/`
- `logs/`
- `ocr_cache/`
- `.ocr-cache/`
- `__pycache__/`
- `build/`
- `dist/`
- packaged `app/` runtime files
- Feishu downloaded images
- Feishu card session JSON files

The files `jianhui 模板.jpg` and `jingzhou 模板.jpg` may contain business
information. Do not publish them to a public repository unless they are replaced
with fully anonymized sample images.

If a real secret was ever committed, deleting the file is not enough. Rotate the
secret in the Feishu/PaddleOCR platform and clean Git history before publishing.

## Development Boundaries

- Keep `orc_calc/core/` behavior stable unless the task explicitly changes the
  business formulas or field normalization rules.
- Feishu-specific changes should stay in `feishu_bot/` or adapter code.
- OCR provider changes should stay in `orc_calc/ocr/`.
- UI-only changes should stay in `static/`.
- Do not make unrelated refactors while fixing a narrow bug.
- Preserve `.env.example` as a safe template with placeholder values only.

## GitHub Upload Checklist

Before the first upload, verify:

```powershell
git status
```

The staged file list must not include:

```text
.env
runtime/
logs/
ocr_cache/
__pycache__/
build/
dist/
jianhui 模板.jpg
jingzhou 模板.jpg
```

Search for obvious secret patterns:

```powershell
rg -n -i "FEISHU_APP_SECRET|PADDLEOCR_ACCESS_TOKEN|private_key|password|cookie|webhook" .
```

Expected matches are only documentation, placeholders, tests, or code reading
environment variables. Real credential values must not appear.

## Notes For Agents

Start by reading `README.md`, this file, and
`docs/project_protection_record.md`. When changing Feishu behavior, also read
`docs/feishu_native_setup.md`. When changing deployment or portable packaging,
read `packaging/portable/README-portable.txt`.

Prefer small, scoped changes and run the focused tests for the touched area.
