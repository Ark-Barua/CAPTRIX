# Contributing to CAPTRIX

Thanks for contributing.

## Scope

CAPTRIX is a Windows-focused desktop recorder built with PySide6 and FFmpeg.
Contributions are welcome for:
- bug fixes
- performance and stability improvements
- UI/UX improvements
- documentation
- tests and tooling

## Development Setup

```powershell
git clone https://github.com/Ark-Barua/CAPTRIX.git
cd CAPTRIX
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Branch and Commit Guidelines

- Create feature branches from `main`.
- Keep commits focused and atomic.
- Use clear commit messages:
  - `feat: ...`
  - `fix: ...`
  - `docs: ...`
  - `refactor: ...`
  - `chore: ...`

## Pull Request Checklist

- The app runs locally without startup errors.
- Changes are limited to the intended scope.
- README/docs are updated when behavior changes.
- New UI behavior is explained in PR description.
- Include before/after screenshots for UI changes when applicable.

## Code Guidelines

- Keep code readable and explicit.
- Prefer small helper functions over long monolithic blocks.
- Preserve existing naming conventions and file structure.
- Avoid introducing platform-specific behavior outside the existing Windows target unless discussed first.

## Reporting Bugs

Please include:
- Windows version
- Python version
- FFmpeg version/build line (`ffmpeg -version`)
- Repro steps
- Error dialog/log tail if available
- Expected vs actual behavior

Use the bug issue template when opening issues.

