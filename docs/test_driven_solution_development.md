# Test-Driven Solution Development

Use this workflow for non-trivial changes in this repository.

1. Write the expected tests first.
   - Capture the behavior the change must add or preserve.
   - Include regression coverage for any bug or risk that motivated the work.
   - Keep tests focused on public behavior, not incidental implementation details.

2. Implement the smallest clean change that makes the tests pass.
   - Prefer existing project patterns and module boundaries.
   - Keep default behavior stable unless the change explicitly requires otherwise.
   - Avoid adding dependencies to the main runtime unless the feature cannot work without them.

3. Add follow-up tests when implementation reveals new edge cases.
   - Cover fallback paths, missing optional dependencies, and failure modes.
   - Do not broaden scope without a test or a written reason.

4. Verify before committing or handing off.
   - Run the targeted test file first.
   - Run the broader suite when the change touches shared behavior.
   - Mention any test that could not be run and why.
