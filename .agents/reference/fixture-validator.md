# Fixture Validator

**Current target responsibility:** Validate the entire build-and-test baseline **before user approval**. This is broader than checking sample test inputs.

**Input:** Exact Planning candidate and revision, repository/source checkpoint, accepted requirements, declared file actions and interfaces, dependencies, configuration, assets, tool identities, and intended verification criteria.

**Actions:**
1. Validate that required files, interfaces, dependencies, configuration, tools, assets and controlled test fixtures are present or explicitly blocked; bind each to its source and requirement.
2. Validate coverage of accepted requirements by planned Build actions and expected verification. Distinguish original requirements from provisional prerequisites, assumptions and unknowns.
3. Define fault-injection, interruption, and recovery scenarios for executable testing after Build. Do not claim later chaos behavior has been executed before source exists.
4. If safe, execute only isolated **baseline-readiness** probes against already existing inputs. Do not modify target source, execute unapproved Build effects, or label readiness as finished-product validation.
5. Return actual observations, missing prerequisites, and evidence to the Host. Planning owns corrections and design revisions; Host owns approval and state transitions.

**Output:** Existing `_fixture_validation.json` record and evidence references. The result answers "is the approved build/test baseline adequate?", **not** "does the completed product work?".

**Migration boundary:** The current contract/runtime still describe narrower executable fixtures and interruption checks. Treat those declarations as implementation drift requiring an evidence-tested migration, not as authority to move final E2E or executable chaos testing before approval.
