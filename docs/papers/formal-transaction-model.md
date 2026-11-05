# Formal Transaction Model and System Invariants for Deterministic Document Editing

This paper provides the formal mathematical specification for PatchDIFF's transaction model, operational semantics, and core system invariants. It defines the state space, transition algebra, sequential applier semantics, and safety theorems governing agent-driven document modifications over the Model Context Protocol (MCP).

For conceptual design and empirical evaluation, see the companion [Concept Paper v6](concept-paper-v6.md). For implementation details and schemas, consult the [Core Runtime Specification](../spec/core-runtime.md), [Data Model](../spec/data-model.md), and [Transaction Formats](../spec/transaction-formats.md).

---

## Abstract

Autonomous coding agents require predictable, bounded, and atomic interfaces when modifying persistent source files and structured configurations. Prevailing approaches rely on unguarded file rewrites or heuristic diff application, exposing documents to silent drift, line-number arithmetic corruption, and partial failure states.

PatchDIFF formalizes agent editing as an optimistic, preconditioned relational transaction. This paper establishes the formal foundation of that model:
1. A metric space over LF-canonical Unicode scalar strings,
2. An algebraic state tuple $\mathcal{S} = (T_0, v_0, h_0)$ combining text, monotonic version counters, and cryptographic content digests,
3. Operational semantics across three transaction classes (`patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`),
4. Mathematical proofs for four core system invariants: Localized Unmatched-Content Preservation, All-or-Nothing Atomicity, Profile-Dispatched Replay Equivalence, and Request-Key Idempotency.

---

## 1. Mathematical Preliminaries and String Metric Spaces

Let $\Sigma$ denote the set of valid Unicode scalar values, defined as the set of code points in the range $U+0000$ to $U+10FFFF$, excluding the UTF-16 surrogate code points $U+D800$ to $U+DFFF$ and the null code point $U+0000$:
$$\Sigma = \{ c \in \mathbb{N}_0 \mid (0 < c < 0xD800 \lor 0xDFFF < c \le 0x10FFFF) \}.$$

Let $\Sigma^*$ denote the free monoid of finite-length sequences over $\Sigma$, normalized to canonical line feed (LF) representation by replacing all carriage return line feed (`\r\n`) and isolated carriage return (`\r`) sequences with single newline characters (`\n`).

For any canonical string $T = \langle c_0, c_1, \dots, c_{n-1} \rangle \in \Sigma^*$:
- $|T| = n$ denotes its length in Unicode code points (scalar values).
- $\varepsilon$ denotes the empty sequence ($|\varepsilon| = 0$).
- For indices $a, b \in \mathbb{N}_0$ satisfying $0 \le a \le b \le |T|$, $T[a:b]$ denotes the contiguous half-open slice $\langle c_a, c_{a+1}, \dots, c_{b-1} \rangle$, with $T[a:a] = \varepsilon$.
- For two strings $A, B \in \Sigma^*$, $A \,\|\, B$ denotes their monoid concatenation, satisfying $|A \,\|\, B| = |A| + |B|$.
- $\text{UTF8}(T)$ denotes the canonical UTF-8 byte serialization of $T$.
- $H: \Sigma^* \to \Sigma^{64}$ denotes the cryptographic hash function computing the lowercase 64-character hexadecimal SHA-256 digest over the UTF-8 representation:
  $$H(T) = \text{SHA256}_{\text{hex}}(\text{UTF8}(T)).$$

---

## 2. Document State Space and Transaction Representation

### 2.1 Authoritative Target Document State

An authoritative target document at rest within the relational persistence substrate is represented as a 3-tuple:
$$\mathcal{S} = (T_0, v_0, h_0) \in \Sigma^* \times \mathbb{N}_0 \times \Sigma^{64}$$
subject to the relational consistency invariant:
$$h_0 = H(T_0).$$

The version counter $v_0$ is a strictly monotonic non-negative integer initialized to $0$ upon document import and incremented by exactly $1$ on each accepted transaction commit.

### 2.2 Transaction Submission Algebra

A transaction submission $\mathcal{X}$ evaluated under an immutable execution profile $\pi$ is formalized as:
$$\mathcal{X} = \bigl(\tau,\; \pi,\; g_v,\; g_h,\; \text{intent},\; \langle o_1, o_2, \dots, o_k \rangle\bigr)$$
where:
- $\tau \in \{\texttt{patchdiff-tx/1},\; \texttt{patchdiff-tx/2},\; \texttt{patchdiff-tx/3}\}$ specifies the protocol grammar.
- $\pi \in \Pi$ represents an immutable, server-selected runtime profile encoding semantic applier flags:
  $$\pi = \bigl(\text{overlap\_aware},\; \text{enforce\_singleton},\; \text{allow\_span},\; \text{allow\_replace\_all},\; \text{allow\_adjacency}\bigr) \in \{0, 1\}^5.$$
  The profile is derived deterministically by the server from $\tau$ and operation capabilities; clients cannot supply arbitrary execution flags.
- $g_v \in \mathbb{N}_0 \cup \{\bot\}$ denotes the optional expected target version guard.
- $g_h \in \Sigma^{64} \cup \{\bot\}$ denotes the optional expected content hash guard, requiring $(g_v, g_h) \neq (\bot, \bot)$.
- $\text{intent} \in \Sigma^+$ denotes the non-empty asserted transaction intent string.
- $\langle o_1, \dots, o_k \rangle$ ($k \ge 1$) denotes an ordered, non-empty sequence of declarative edit operations.

---

## 3. Precondition Verification and Admission Control

Before evaluating any operation $o_i$, the transaction monitor verifies the state precondition guard against the authoritative document state $\mathcal{S} = (T_0, v_0, h_0)$:
$$\text{GuardOK}(\mathcal{S}, g_v, g_h) \iff (g_v = \bot \lor g_v = v_0) \;\land\; (g_h = \bot \lor g_h = h_0).$$

### 3.1 Verification Order and Error Typing

When both $g_v$ and $g_h$ are present, the version precondition is evaluated first:
1. If $g_v \neq \bot \land g_v \neq v_0$, the transaction aborts with rejection code `target_version_mismatch`.
2. If $g_v = v_0 \land g_h \neq \bot \land g_h \neq h_0$, the transaction aborts with rejection code `target_hash_mismatch`.

Both rejections occur at stage `precondition_guard`, reporting `protocol_valid: null` and `transaction_valid: null`. The document state remains identically $\mathcal{S}$.

### 3.2 Whole-Target Replacement Admission Bounds

For whole-target replacement transactions ($\tau = \texttt{patchdiff-tx/3}$), fresh submissions must satisfy strict size admission bounds prior to entering the applier:
$$|r_1| \le 1{,}000{,}000 \quad \text{and} \quad |\text{UTF8}(r_1)| \le 1{,}048{,}576 \text{ bytes}.$$
Submissions exceeding either limit reject immediately with `invalid_argument` (`code: replacement_too_large`), preventing unbounded allocation under the held row lock.

---

## 4. Operational Semantics of Transaction Classes

When $\text{GuardOK}(\mathcal{S}, g_v, g_h)$ evaluates to true, the core applier initializes the intermediate in-memory buffer sequence:
$$T^{(0)} = T_0.$$
The operations $o_1, \dots, o_k$ execute sequentially. Each operation $o_i$ ($1 \le i \le k$) maps the intermediate buffer $T^{(i-1)}$ to either a resolved span $[s_i, e_i)$ with replacement string $r_i \in \Sigma^*$, or to a failure token $\bot$.

### 4.1 Class 1: Localized Exact-Match Operations (`tx/1` and `tx/2` match)

An exact-match operation is defined as:
$$o_i = \text{Match}(m_i, r_i, \text{occ}_i, \alpha_i, \beta_i)$$
where $m_i \in \Sigma^+$ is a non-empty pattern string, $r_i \in \Sigma^*$ is the replacement string, $\text{occ}_i \in \mathbb{N}_1 \cup \{\bot\}$ is the 1-based occurrence index, and $\alpha_i, \beta_i \in \Sigma^* \cup \{\bot\}$ are optional prefix and suffix anchors.

#### Step 1: Exact Occurrence Enumeration
The exact occurrence sequence $\text{Occ}_\pi(T, m)$ enumerates all half-open intervals $[s, s + |m|)$ such that $T[s : s + |m|] = m$:
$$\text{Occ}_\pi(T, m) = \langle [s_j, s_j + |m|) \mid 0 \le s_j \le |T| - |m| \land T[s_j : s_j + |m|] = m \rangle_{j=1}^M$$
ordered such that $s_1 < s_2 < \dots < s_M$.

Crucially, the scan advances by 1 code point ($s_{j+1} \ge s_j + 1$) rather than by $|m|$, capturing overlapping occurrences (for example, finding two occurrences of `"aba"` in `"ababa"` at $[0, 3)$ and $[2, 5)$).

- If $M = 0$, the operation rejects with `match_absent` (or `sequential_match_invalid` when $i > 1$ and $m_i$ existed in $T_0$ but was consumed by an earlier operation $o_j$, $j < i$).
- If $M > 1$ and $\text{occ}_i = \bot \land \alpha_i = \bot \land \beta_i = \bot$, the operation rejects with `match_ambiguous`.

#### Step 2: Global Occurrence Index Selection
Let candidate list $C_0 = \text{Occ}_\pi(T^{(i-1)}, m_i)$.
If $\text{occ}_i \neq \bot$:
- If $1 \le \text{occ}_i \le |C_0|$, select $C_1 = \langle C_0[\text{occ}_i - 1] \rangle$.
- Otherwise, reject with `disambiguation_invalid`.
If $\text{occ}_i = \bot$, set $C_1 = C_0$.

Under the singleton-selector enforcement rule ($\pi.\text{enforce\_singleton} = 1$), this selection step is validated even when $|C_0| = 1$, ensuring stale selectors (such as $\text{occ}_i = 2$ when only one occurrence exists) reject cleanly.

#### Step 3: Conjunctive Anchor Filtering
For each span $[s, e) \in C_1$, verify prefix and suffix containment:
$$\text{AnchorOK}([s, e), \alpha_i, \beta_i) \iff (\alpha_i = \bot \lor \alpha_i \sqsubseteq T^{(i-1)}[0:s]) \;\land\; (\beta_i = \bot \lor \beta_i \sqsubseteq T^{(i-1)}[e:|T^{(i-1)}|])$$
where $A \sqsubseteq B$ denotes that $A$ occurs as a substring anywhere within $B$.

The filtered candidate set is:
$$C_2 = \{ [s, e) \in C_1 \mid \text{AnchorOK}([s, e), \alpha_i, \beta_i) \}.$$

The operation succeeds if and only if $|C_2| = 1$, yielding resolved span $[s_i, e_i) = C_2[0]$. If $|C_2| = 0$ or $|C_2| > 1$, it rejects with `disambiguation_invalid`.

### 4.2 Class 2: Localized Guarded Code-Point Span Operations (`tx/2` span)

A guarded span operation is defined as:
$$o_i = \text{Span}(s_i, e_i, x_i, r_i, b_i, a_i)$$
where $0 \le s_i \le e_i \le |T^{(i-1)}|$, $x_i \in \Sigma^*$ is the expected text satisfying $|x_i| = e_i - s_i$, $r_i \in \Sigma^*$ is the replacement text, and $b_i, a_i \in \Sigma^* \cup \{\bot\}$ are optional immediate adjacency guards.

The operation succeeds on $T^{(i-1)}$ if and only if all three predicates hold:
1. **Bounds Integrity:**
   $$0 \le s_i \le e_i \le |T^{(i-1)}| \quad (\text{else } \bot \text{ with } \texttt{span\_out\_of\_bounds}).$$
2. **Exact Substring Verification:**
   $$T^{(i-1)}[s_i : e_i] = x_i \quad (\text{else } \bot \text{ with } \texttt{span\_expected\_text\_mismatch}, \text{check: } \texttt{expected\_text}).$$
   When $s_i = e_i$ and $x_i = \varepsilon$, this defines a zero-length insertion at code-point offset $s_i$.
3. **Immediate Adjacency Preconditions:**
   When $b_i \neq \bot$, require $s_i \ge |b_i| \land T^{(i-1)}[s_i - |b_i| : s_i] = b_i$.
   When $a_i \neq \bot$, require $e_i + |a_i| \le |T^{(i-1)}| \land T^{(i-1)}[e_i : e_i + |a_i|] = a_i$.
   Failure of either condition rejects with `span_expected_text_mismatch` (`check: expected_before` or `expected_after`).

### 4.3 Class 3: Guarded Whole-Target Replacement (`tx/3`)

A whole-target replacement operation is defined as:
$$k = 1, \quad o_1 = \text{ReplaceAll}(r_1), \quad r_1 \in \Sigma^*.$$
The operation unconditionally selects the full target span:
$$[s_1, e_1) = [0, |T^{(0)}|)$$
and maps $T^{(0)}$ directly to $r_1$, subject to the fresh admission bounds defined in Section 3.2.

### 4.4 Buffer Transformation Function

When operation $o_i$ resolves to span $[s_i, e_i)$ with replacement text $r_i$, the next intermediate buffer state is constructed via concatenation:
$$T^{(i)} = T^{(i-1)}[0 : s_i] \,\|\, r_i \,\|\, T^{(i-1)}\bigl[e_i : |T^{(i-1)}|\bigr].$$

The code-point length of the resulting buffer is:
$$|T^{(i)}| = |T^{(i-1)}| - (e_i - s_i) + |r_i|.$$

---

## 5. Core System Invariants and Formal Proofs

### Invariant 1: Localized Unmatched-Content Preservation

> **Theorem 1 (Content Preservation Outside Resolved Spans).**
> For any localized operation $o_i \in \{\text{Match}, \text{Span}\}$ resolving to span $[s_i, e_i)$ on intermediate buffer $T^{(i-1)}$ with replacement string $r_i \in \Sigma^*$, the prefix preceding $s_i$ and the suffix succeeding $e_i$ are preserved code-point-for-code-point:
> $$T^{(i)}[0 : s_i] = T^{(i-1)}[0 : s_i]$$
> and
> $$T^{(i)}\bigl[s_i + |r_i| : |T^{(i)}|\bigr] = T^{(i-1)}\bigl[e_i : |T^{(i-1)}|\bigr].$$

*Proof.*
By definition of the buffer transformation function (Section 4.4):
$$T^{(i)} = A \,\|\, B \,\|\, C$$
where $A = T^{(i-1)}[0 : s_i]$, $B = r_i$, and $C = T^{(i-1)}[e_i : |T^{(i-1)}|]$.
1. The prefix slice $T^{(i)}[0 : s_i]$ covers exactly $|A| = s_i$ code points. By monoid concatenation properties, this slice is identically $A = T^{(i-1)}[0 : s_i]$.
2. The replacement block $B$ occupies the interval $[s_i, s_i + |r_i|)$.
3. The suffix slice starts at offset $s_i + |r_i|$ and extends to $|T^{(i)}| = s_i + |r_i| + |C|$. The length of this slice is $|C| = |T^{(i-1)}| - e_i$. By concatenation properties, this slice is identically $C = T^{(i-1)}[e_i : |T^{(i-1)}|]$.
Therefore, no code point outside $[s_i, e_i)$ is altered. $\blacksquare$

*Remark on Scope:* Whole-target replacement (`tx/3`) is intentionally excluded from Invariant 1, as its explicit contract replaces the entire document span $[0, |T_0|)$ under mandatory optimistic version/hash guards.

---

### Invariant 2: All-or-Nothing Per-Target Atomic State Transition

> **Theorem 2 (Per-Target Atomic Transitions).**
> Let $\mathcal{S} = (T_0, v_0, h_0)$ be the authoritative target state. For any submission $\mathcal{X} = (\tau, \pi, g_v, g_h, \text{intent}, \langle o_1, \dots, o_k \rangle)$:
> 1. If $\neg\text{GuardOK}(\mathcal{S}, g_v, g_h)$ or if any operation $o_i \in \langle o_1, \dots, o_k \rangle$ resolves to $\bot$, the committed document state remains identically:
>    $$\mathcal{S}' = \mathcal{S} = (T_0, v_0, h_0).$$
> 2. If and only if $\text{GuardOK}(\mathcal{S}, g_v, g_h)$ holds and all $k$ operations succeed sequentially ($o_i \neq \bot$ for all $1 \le i \le k$), the document state advances atomically to:
>    $$\mathcal{S}' = \bigl(T^{(k)},\; v_0 + 1,\; H(T^{(k)})\bigr).$$

*Proof.*
The execution pipeline separates simulation from persistence:
1. When $\mathcal{X}$ arrives, a PostgreSQL row lock is acquired:
   $$\texttt{SELECT ... FOR UPDATE ON cloud\_target\_files WHERE id = target\_file\_id}.$$
2. If precondition checks fail, or if during sequential in-memory simulation any $o_i$ produces $\bot$, the server issues no SQL `UPDATE` on `cloud_target_files`. Instead, it records a rejection record in `append_only_pdcp_logs` and commits the transaction without mutating the target row. Hence, $\mathcal{S}' = \mathcal{S}$.
3. Only when all $k$ operations produce valid intermediate buffers $T^{(1)}, \dots, T^{(k)}$ does the service execute:
   $$\texttt{UPDATE cloud\_target\_files SET current\_content = } T^{(k)}, \texttt{ version = } v_0 + 1, \texttt{ current\_hash = } H(T^{(k)})$$
   alongside the accepted attempt in `append_only_pdcp_logs` and derived change records in `append_only_manifest_ledger` within the same database transaction.
4. By PostgreSQL ACID transaction guarantees, either all updates commit or all roll back. Thus, partial intermediate states $T^{(1)}, \dots, T^{(k-1)}$ are never committed. $\blacksquare$

---

### Invariant 3: Deterministic Execution and Profile-Dispatched Replay Equivalence

> **Theorem 3 (Replay Determinism).**
> Let $T_{\text{init}} \in \Sigma^*$ be the initial document content recorded in a snapshot with hash $h_{\text{init}} = H(T_{\text{init}})$. Let $\langle (\mathcal{X}_1, \pi_1), (\mathcal{X}_2, \pi_2), \dots, (\mathcal{X}_m, \pi_m) \rangle$ be the ordered sequence of accepted transactions recorded in `append_only_pdcp_logs`.
>
> Re-applying each transaction $\mathcal{X}_j$ sequentially under its recorded immutable execution profile $\pi_j$ starting from $T_{\text{init}}$ is a pure deterministic function that yields the exact committed state:
> $$\text{Replay}\bigl(T_{\text{init}},\; \langle (\mathcal{X}_j, \pi_j) \rangle_{j=1}^m\bigr) = \bigl(T_m,\; m,\; H(T_m)\bigr).$$

*Proof.*
We proceed by mathematical induction on log length $m$.
- **Base Step ($m = 0$):**
  $\text{Replay}(T_{\text{init}}, \emptyset) = (T_{\text{init}}, 0, H(T_{\text{init}}))$. This trivially equals the initial state $(T_0, 0, h_0)$ with $h_0 = H(T_{\text{init}})$.
- **Inductive Step:**
  Assume the theorem holds for $m - 1$ accepted transactions, yielding state $(T_{m-1}, m-1, H(T_{m-1}))$.
  Transaction $\mathcal{X}_m$ was accepted in historical execution, which implies:
  $$\text{GuardOK}\bigl((T_{m-1}, m-1, H(T_{m-1})),\; g_v^{(m)},\; g_h^{(m)}\bigr) = \text{true}.$$
  Because the applier is a pure mathematical function of $(T_{m-1}, \mathcal{X}_m, \pi_m)$ containing no random variables, external clock reads, or non-deterministic hash iterations:
  1. LF canonicalization is deterministic and idempotent.
  2. String slicing and exact code-point index lookups in $\Sigma^*$ are deterministic.
  3. Occurrence list $\text{Occ}_{\pi_m}(T_{m-1}, m_i)$ depends strictly on the static string values under profile $\pi_m$.
  4. Concatenation $T^{(i-1)}[0:s_i] \,\|\, r_i \,\|\, T^{(i-1)}[e_i:]$ is deterministic.
  Therefore, the final replayed buffer $T^{(k)}$ produced by $\mathcal{X}_m$ evaluates to the exact string $T_m$.
  The version counter advances to $(m - 1) + 1 = m$, and the recomputed digest evaluates to $H(T_m) = \text{SHA256}_{\text{hex}}(\text{UTF8}(T_m))$.
By induction, replay reproduces the exact materialized state for all $m \ge 0$. $\blacksquare$

---

### Invariant 4: Request-Key Idempotency

> **Theorem 4 (Strict Request-Key Idempotency).**
> Let $F$ denote a target file identifier and $q \in \Sigma^+$ denote a non-null client request identifier. Let $\mathcal{R}(F, q)$ denote the set of transaction submissions evaluated for target $F$ with key $q$.
> 1. At most one submission in $\mathcal{R}(F, q)$ is ever executed against the document applier.
> 2. Any subsequent submission $\mathcal{X}' \in \mathcal{R}(F, q)$ whose request fingerprint matches the recorded fingerprint returns the exact recorded terminal outcome with response flag:
>    $$\texttt{deduplicated: true}$$
>    without re-evaluating operations or mutating document state.
> 3. Any subsequent submission $\mathcal{X}'' \in \mathcal{R}(F, q)$ whose request fingerprint diverges from the recorded fingerprint is rejected with:
>    $$\texttt{failure\_reason: "context\_invalid"},\; \texttt{diagnostic.code: "request\_key\_conflict"}$$
>    without mutating document state.

*Proof.*
1. Under the row lock acquired on $F$, the service queries `append_only_pdcp_logs` for an existing record matching $(F, q)$.
2. If no record exists, the transaction is fresh. The key $q$ is bound to the attempt record inserted during commit. By the unique constraint on $(F, q)$ across active attempt records, at most one attempt can commit with key $(F, q)$.
3. If an existing record is found, the service compares the SHA-256 fingerprint of the incoming request payload with the persisted `pdcp_content_hash`:
   - If hashes match, the server constructs the response directly from the persisted record, sets `deduplicated = true`, and returns immediately. Target state $\mathcal{S}$ is unchanged.
   - If hashes differ, a client is attempting to reuse an existing idempotency key with conflicting payload data. The transaction aborts with `request_key_conflict`. The rejection is logged with `client_request_id = NULL` to ensure the original $(F, q)$ binding is preserved. Target state $\mathcal{S}$ is unchanged. $\blacksquare$

---

## 6. Implementation Traceability and Verification Matrix

Every mathematical construct defined in this paper corresponds directly to verified software modules within the PatchDIFF reference implementation:

| Formal Construct | Implementation Module | Automated Test Coverage |
| :--- | :--- | :--- |
| **String Metric & Normalization ($\Sigma^*$, LF)** | `backend/core/applier.py:normalize_line_endings` | `tests/unit/test_applier.py` |
| **State Space ($\mathcal{S} = (T_0, v_0, h_0)$)** | `backend/models/target_file.py:CloudTargetFile` | `tests/integration/test_target_files.py` |
| **Precondition Guard ($\text{GuardOK}$)** | `backend/services/transactions.py:_verify_guards` | `tests/integration/test_concurrency.py` |
| **Exact Occurrence Scan ($\text{Occ}_\pi$)** | `backend/core/applier.py:_find_all_occurrences` | `tests/unit/test_applier.py` |
| **Class 1 Applier (`tx/1` exact match)** | `backend/core/applier.py:apply_exact_match_transaction` | `tests/unit/test_applier.py` |
| **Class 2 Applier (`tx/2` guarded span)** | `backend/core/applier.py:apply_operations_transaction` | `tests/unit/test_span_operations.py` |
| **Class 3 Applier (`tx/3` whole replacement)** | `backend/core/applier.py:apply_replacement_transaction` | `tests/unit/test_applier.py` |
| **Invariant 1 (Content Preservation)** | `backend/core/applier.py` | `tests/verification/offline_eval.py` |
| **Invariant 2 (All-or-Nothing Atomicity)** | `backend/services/transactions.py:submit_transaction` | `tests/integration/test_transactions.py` |
| **Invariant 3 (Replay Equivalence)** | `backend/services/replay.py:replay_target_file` | `tests/integration/test_replay.py` |
| **Invariant 4 (Request-Key Idempotency)** | `backend/services/transactions.py:_check_idempotency` | `tests/integration/test_idempotency.py` |

---

## References

1. **Model Context Protocol Specification:** Anthropic, *Model Context Protocol Specification (JSON-RPC 2.0 Transport & Tool Calling)*, `https://modelcontextprotocol.io/`.
2. **IETF RFC 6902:** P. Bryan and M. Nottingham, *JavaScript Object Notation (JSON) Patch*, RFC 6902, April 2013.
3. **Unicode Standard Annex #29:** M. Davis, *Unicode Text Segmentation (Extended Grapheme Clusters)*, Unicode Consortium.
4. **Optimistic Concurrency Control:** H. T. Kung and J. T. Robinson, *"On Optimistic Methods for Concurrency Control,"* ACM Transactions on Database Systems (TODS), 6(2):213-226, 1981.
5. **PatchDIFF Companion Papers:**
   - [Concept Paper v6](concept-paper-v6.md): High-level system architecture, comparative paradigm analysis, and empirical evaluation.
   - [Modernization Architecture](modernization-architecture.md): Systems architecture, profile boundaries, and technical reconciliation.
   - [Product Change Record](product-change-record.md): Audit record of architectural evolution and profile definitions.
