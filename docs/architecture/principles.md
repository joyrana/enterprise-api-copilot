# Architecture Principles

These principles are binding for code review. Each one names the mechanism that enforces it.

1. **The model is never an authority.** Authorization, approval and environment
   selection are decided by code outside the model. The model can *propose* a skill
   call; the skill runtime decides whether it runs. *Enforced by:* `skills/runtime/runtime.py`
   is the only execution path; MCP and agent adapters call it, never a skill directly.

2. **Discovery is separate from execution.** Listing or describing skills and APIs has
   no side effects and needs only read permissions. Execution needs an explicit
   permission, and side-effecting execution needs an approval bound to the exact call.

3. **Untrusted by default.** Retrieved documents, OpenAPI descriptions, tool output and
   upstream API responses are data. They are delimited when placed in model context,
   scanned for instruction-like content, and can never change policy, target environment
   or arguments after approval.

4. **Deterministic where possible.** Known operations use deterministic routing and
   templated plans. Model calls are reserved for steps that need language understanding,
   and every model output is parsed into a typed schema before use.

5. **Bounded everything.** Plans have a maximum step count; the executor has tool-call,
   retry and wall-clock budgets; outbound HTTP has timeouts and response-size limits.

6. **Read-only and sandbox by default.** Production writes are disabled unless an
   environment is explicitly allowlisted *and* a policy grants the permission *and*
   an approval is recorded.

7. **One canonical home per capability.** No parallel trees. Compatibility shims exist
   only with a tested caller and a removal date.

8. **Evidence over claims.** A feature is done when tests demonstrate it. Benchmarks are
   reproducible from a commit, a dataset hash and a config; numbers are never typed in
   by hand.

9. **Replaceable providers.** LLMs, embedders, vector stores, gateways and policy
   decision points sit behind small interfaces with an offline implementation, so the
   whole system runs and is evaluated without paid credentials.

10. **Secrets never travel.** Tokens and credentials are redacted before logging,
    tracing, model submission, evaluation artifacts and generated code samples.

11. **Smallest graph that works.** No agent swarms or extra services for novelty. A new
    node or service must be justified by a test or a benchmark.
