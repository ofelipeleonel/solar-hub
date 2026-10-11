## Summary of Changes
Please provide a brief overview of the changes implemented in this pull request.

## Related Issues
Closes # (issue number)

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance improvement / Refactoring

## Quota & Architectural Checklist
- [ ] Does NOT hardcode regional electric tariffs or monetary conversion policies.
- [ ] Adheres to the Budget Keeper guidelines (does not cause runaway API calls).
- [ ] Reads from local SQLite when exposing stored data to external consumers.

## Verification & Tests
- [ ] Added unit tests covering the new functionality.
- [ ] All tests pass locally (`uv run pytest`).
- [ ] Linter checks pass locally (`uv run ruff check .`).
