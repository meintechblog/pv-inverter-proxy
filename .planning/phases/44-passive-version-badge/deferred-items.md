# Deferred Items — Phase 44

Items discovered during Plan 44-01 execution that are out of scope for the
updater backend but should be addressed elsewhere.

## 1. Pre-existing webapp test failure

- **Test:** `tests/test_webapp.py::test_config_get_venus_defaults`
- **Status:** Already failing on HEAD before Plan 44-01 started.
- **Relation to 44-01:** Zero. None of the files touched by this plan are
  in webapp.py's dependency graph.
- **Action:** Leave alone per scope boundary rule. Investigate in Phase 44-02
  (which DOES touch webapp.py) or file a separate fix commit.
