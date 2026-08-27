# VALIDATE

`artifact2dsl validate LEFT RIGHT [...]` compares claims only when their
documents share an explicit namespace. `--rules artifact2dsl.rules/v1.json`
selects facts across different namespaces and permits `exact` or `numeric`
comparison with a declared tolerance.

Validation is observation-only. `blocked` means facts conflict, are missing,
are ambiguous, or an input converter produced an error. It is not permission
to edit either source.
