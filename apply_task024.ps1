# Run from the root of your micky-ai repo checkout.
# Usage: .\apply_task024.ps1 -ZipPath "C:\path\to\task024_changed_files.zip"

param(
    [string]$ZipPath = "$PSScriptRoot\task024_changed_files.zip"
)

$RepoRoot = Get-Location
Write-Host "Repo root: $RepoRoot"
Write-Host "Zip: $ZipPath"

if (-not (Test-Path $ZipPath)) {
    Write-Error "Zip not found at $ZipPath"
    exit 1
}

# Extract, overwriting the 4 changed/new files in place.
Expand-Archive -Path $ZipPath -DestinationPath $RepoRoot -Force

# Set up / reuse a venv so deps match the project's pyproject.toml.
if (-not (Test-Path ".\.venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\pip install -e ".[dev]" | Out-Null

# Run the Task 024 tests plus the full regression suite.
& .\.venv\Scripts\python -m pytest tests\test_hypothesis_scoring.py tests\test_hypothesis_score_interpretation.py -q
& .\.venv\Scripts\python -m pytest -q

# Lint/format check on the touched files.
& .\.venv\Scripts\ruff check src\rop\services\hypothesis_scoring.py src\rop\schemas\hypothesis_score.py src\rop\api\sessions.py tests\test_hypothesis_score_interpretation.py
& .\.venv\Scripts\black --check src\rop\services\hypothesis_scoring.py src\rop\schemas\hypothesis_score.py src\rop\api\sessions.py tests\test_hypothesis_score_interpretation.py

Write-Host "`nDone. Review 'git status' / 'git diff' before committing."
