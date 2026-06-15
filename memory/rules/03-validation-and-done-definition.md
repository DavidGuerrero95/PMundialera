# Validation and done definition

Minimum validation after code changes:

```powershell
ruff check .
mypy src
pytest
```

For GolPredictor changes, also run:

```powershell
pmundialera golpredictor login-check
pmundialera golpredictor groups
```

Do not claim live submission success unless the command completed with
`submit=True` and no errors.
