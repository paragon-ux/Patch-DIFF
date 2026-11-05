# Formal Transaction Model and System Invariants for Deterministic Document Editing

This paper provides the formal mathematical specification for PatchDIFF's transaction model, operational semantics, and core system invariants. It defines the discrete string state space, transition algebra, sequential applier semantics, and safety theorems governing agent-driven document modifications over the Model Context Protocol (MCP).

Repository invariants in [AGENTS.md](https://github.com/paragon-ux/Patch-DIFF/blob/main/AGENTS.md) govern the normative boundaries of this specification. For conceptual design, comparative analysis, and empirical evaluations, see [Concept Paper v6](concept-paper-v6.md). For executable schemas and implementation details, consult the normative specifications: [Core Runtime Specification](../spec/core-runtime.md), [Data Model](../spec/data-model.md), [Transaction Formats](../spec/transaction-formats.md), [MCP Tool Contracts](../spec/mcp-tools.md), and [Profiles](../spec/profiles/index.md).

---

## Abstract

Autonomous coding agents require predictable, bounded, and atomic interfaces when modifying persistent source files and structured configurations. Prevailing approaches rely on unguarded file rewrites or heuristic diff application, exposing documents to silent drift, line-number arithmetic corruption, and partial failure states.

PatchDIFF formalizes agent editing as a deterministic, preconditioned relational transaction. This paper establishes the mathematical foundation of that model:
1. A discrete string domain over LF-canonical Unicode scalar sequences excluding NUL and surrogate code points, alongside a 64-character hexadecimal digest space,
2. An authoritative relational state tuple $\mathcal{S} = (T_0, v_0, h_0)$ combining canonical text, a monotonic version counter, and a cryptographic content digest,
3. Operational semantics across three public declarative transaction classes (`patchdiff-tx/1`, `patchdiff-tx/2`, and `patchdiff-tx/3`), noting internal structural batch formats (`patchdiff-observed-batch/1`),
4. Mathematical proofs for four core system invariants: Localized Content Preservation Outside Resolved Spans, All-or-Nothing Per-Target Atomicity, Profile-Dispatched Replay Equivalence, and Request-Key Idempotency.

---

## 1. Mathematical Preliminaries and String Domain

Let $\mathcal{U}$ denote the set of valid Unicode scalar values according to Unicode Standard Annex #29:

$$
\mathcal{U} = \{ c \in \mathbb{N}_0 \mid (0 \le c < 0xD800) \lor (0xDFFF < c \le 0x10FFFF) \}.
$$

To guarantee safe persistence within PostgreSQL `TEXT` and `JSONB` columns without encoding errors or string truncation, PatchDIFF defines the admissible document alphabet $\Sigma$ by strictly excluding the NUL code point $0$ ($U+0000$):

$$
\Sigma = \mathcal{U} \setminus \{0\} = \{ c \in \mathbb{N}_0 \mid (0 < c < 0xD800) \lor (0xDFFF < c \le 0x10FFFF) \}.
$$

Let $\Sigma^*$ denote the free monoid of finite-length sequences over $\Sigma$.

### 1.1 Canonical Normalization

Cross-platform line-ending discrepancies are eliminated by mapping raw text through the canonicalization function $\text{canon}: \mathcal{V} \to \Sigma^*$, where $\mathcal{V}$ is arbitrary raw input text or UTF-8 bytes. The canonicalization function converts all CRLF (`\r\n`) pairs into LF (`\n`), and converts all standalone CR (`\r`) characters into LF (`\n`):

$$
\text{canon}(s) = \text{replace}\bigl(\text{replace}(s, \texttt{"\textbackslash r\textbackslash n"}, \texttt{"\textbackslash n"}), \texttt{"\textbackslash r"}, \texttt{"\textbackslash n"}\bigr).
$$

Canonicalization preserves all surrounding whitespace, indentation, and Unicode code points without trimming or applying Unicode normalizations (such as NFC or NFD). Every target document, match string, replacement payload, expected text guard, and anchor string is canonicalized via $\text{canon}$ before matching, hashing, or storing.

### 1.2 String Operations and Indexing

For any canonical string $T = \langle c_0, c_1, \dots, c_{n-1} \rangle \in \Sigma^*$:
- $|T| = n$ denotes its length in Unicode code points (scalar values).
- $\varepsilon$ denotes the empty sequence with $|\varepsilon| = 0$.
- For indices $a, b \in \mathbb{N}_0$ satisfying $0 \le a \le b \le |T|$, $T[a:b]$ denotes the contiguous half-open slice $\langle c_a, c_{a+1}, \dots, c_{b-1} \rangle$, with $T[a:a] = \varepsilon$.
- For strings $A, B \in \Sigma^*$, $A \,\|\, B$ denotes their monoid concatenation, satisfying $|A \,\|\, B| = |A| + |B|$.
- $\text{UTF8}(T)$ denotes the standard UTF-8 byte serialization of $T$.

### 1.3 Cryptographic Digest Space

Let $\Sigma_{\text{hex}} = \{ \texttt{0}, \texttt{1}, \dots, \texttt{9}, \texttt{a}, \texttt{b}, \texttt{c}, \texttt{d}, \texttt{e}, \texttt{f} \}$.

The cryptographic digest function $H: \Sigma^* \to \Sigma_{\text{hex}}^{64}$ computes the lowercase 64-character hexadecimal SHA-256 digest over the canonical UTF-8 bytes:

$$
H(T) = \text{SHA256}_{\text{hex}}(\text{UTF8}(T)).
$$

By definition, $|H(T)| = 64$ for all $T \in \Sigma^*$.

---

## 2. Document State Space and Transaction Representation

### 2.1 Authoritative Target Document State

An authoritative target document at rest within PostgreSQL is represented as a 3-tuple:

$$
\mathcal{S} = (T_0, v_0, h_0) \in \Sigma^* \times \mathbb{N}_0 \times \Sigma_{\text{hex}}^{64}
$$

subject to the relational consistency invariant:

$$
h_0 = H(T_0).
$$

The version counter $v_0$ is a strictly monotonic non-negative integer initialized to $0$ upon document import and incremented by exactly $1$ on each accepted, non-duplicate transaction commit.

### 2.2 Transaction Submission Algebra

A public transaction proposal $\mathcal{X}$ evaluated under an immutable runtime execution profile $p$ is formalized as:

$$
\mathcal{X} = \bigl(\tau,\; p,\; g_v,\; g_h,\; \text{intent},\; \langle o_1, o_2, \dots, o_k \rangle\bigr)
$$

where:
- $\tau \in \{\texttt{patchdiff-tx/1},\; \texttt{patchdiff-tx/2},\; \texttt{patchdiff-tx/3}\}$ specifies the public transaction protocol.
- $p = (\tau, \nu)$ combines the protocol version $\tau$ and the recorded immutable runtime version string $\nu$ (such as `patchdiff-mvp-0.2.2`, `patchdiff-mvp-0.3.0`, `patchdiff-mvp-0.4.0`, or `patchdiff-mvp-0.5.0`). The runtime version maps deterministically to a boolean feature profile:
  
  $$
  \pi = \text{ResolveProfile}(\nu) = \bigl(\text{overlap\_aware},\; \text{enforce\_singleton},\; \text{span\_ops},\; \text{replace\_all\_ops},\; \text{span\_context}\bigr) \in \{0, 1\}^5.
  $$
  
- $g_v \in \mathbb{N}_0 \cup \{\bot\}$ denotes the optional expected target version guard.
- $g_h \in \Sigma_{\text{hex}}^{64} \cup \{\bot\}$ denotes the optional expected content hash guard, requiring $(g_v, g_h) \neq (\bot, \bot)$.
- $\text{intent} \in \Sigma^+$ denotes the non-empty asserted transaction intent string.
- $\langle o_1, \dots, o_k \rangle$ ($k \ge 1$) denotes an ordered, non-empty sequence of declarative edit operations.

Internal multi-scope batched refactorings discovered through AST Waymark coordinates use the internal format `patchdiff-observed-batch/1` (`patchdiff-observed-batch-r1`), compiling up to 32 disjoint scope operations into an atomic bundle.

---

## 3. Precondition Verification and Admission Control

Before evaluating any operation $o_i$, the transaction monitor verifies the state precondition guard against the authoritative target state $\mathcal{S} = (T_0, v_0, h_0)$:

$$
\text{GuardOK}(\mathcal{S}, g_v, g_h) \iff (g_v = \bot \lor g_v = v_0) \;\land\; (g_h = \bot \lor g_h = h_0).
$$

### 3.1 Verification Order and Error Typing

When both $g_v$ and $g_h$ are present, the version precondition is evaluated first:
1. If $g_v \neq \bot \land g_v \neq v_0$, the transaction rejects with code `target_version_mismatch`.
2. If $g_v = v_0 \land g_h \neq \bot \land g_h \neq h_0$, the transaction rejects with code `target_hash_mismatch`.

Both rejections occur at stage `precondition_guard`, reporting `protocol_valid: null` and `transaction_valid: null`. The target state remains identically $\mathcal{S}$.

### 3.2 Service Boundary: Key Idempotency and Fresh Admission

The service boundary evaluates client request keys before admitting a fresh submission into the applier:
1. **Idempotency Lookup:** If a submission carries a valid `client_request_id` matching an existing log row for this target, the server checks request fingerprints. If fingerprints match, the server returns the recorded outcome immediately with `deduplicated: true`. Target state remains unchanged, and no new attempt log row is inserted. If fingerprints differ, the server rejects with `context_invalid` (code `request_key_conflict`) and audits the conflict attempt under a NULL key, leaving the original binding intact.
2. **Fresh Admission Limits for `patchdiff-tx/3`:** Fresh whole-target replacement proposals must satisfy size bounds on both raw and canonical text:
   
   $$
   \max\bigl(|r_{\text{raw}}|, |r_{\text{canon}}|\bigr) \le 1{,}000{,}000 \text{ code points}
   $$
   
   and
   
   $$
   \max\bigl(|\text{UTF8}(r_{\text{raw}})|, |\text{UTF8}(r_{\text{canon}})|\bigr) \le 1{,}048{,}576 \text{ bytes}.
   $$
   
   Submissions exceeding either limit reject immediately with `invalid_argument` (code `replacement_too_large`), preventing unbounded allocation under the held row lock without mutating state or persisting an attempt log row.
3. **Replay Independence:** Replay operations verify historical records against recorded profiles and do not reapply fresh admission limits.

---

## 4. Operational Semantics of Transaction Classes

When $\text{GuardOK}(\mathcal{S}, g_v, g_h)$ evaluates to true and admission succeeds, the core applier initializes the intermediate in-memory buffer sequence:

$$
T^{(0)} = T_0.
$$

Operations $o_1, \dots, o_k$ execute sequentially. Each operation $o_i$ ($1 \le i \le k$) maps intermediate buffer $T^{(i-1)}$ to either a resolved span $[s_i, e_i)$ with replacement string $r_i \in \Sigma^*$, or to a failure token $\bot$.

### 4.1 Class 1: Localized Exact-Match Operations (`tx/1` and `tx/2` match)

An exact-match operation is defined as:

$$
o_i = \text{Match}(m_i, r_i, \text{occ}_i, \alpha_i, \beta_i)
$$

where $m_i \in \Sigma^+$ is a non-empty pattern string, $r_i \in \Sigma^*$ is the replacement string, $\text{occ}_i \in \mathbb{N}_1 \cup \{\bot\}$ is the 1-based occurrence index, and $\alpha_i, \beta_i \in \Sigma^* \cup \{\bot\}$ are optional prefix and suffix anchors.

#### Step 1: Exact Occurrence Enumeration
The exact occurrence sequence $\text{Occ}_\pi(T, m)$ enumerates all half-open intervals $[s, s + |m|)$ such that $T[s : s + |m|] = m$:

$$
\text{Occ}_\pi(T, m) = \langle [s_j, s_j + |m|) \mid 0 \le s_j \le |T| - |m| \land T[s_j : s_j + |m|] = m \rangle_{j=1}^M
$$

ordered such that $s_1 < s_2 < \dots < s_M$.

When $\pi.\text{overlap\_aware} = 1$, the scan advances by 1 code point ($s_{j+1} \ge s_j + 1$) rather than by $|m|$, capturing overlapping occurrences (for example, finding two occurrences of `"aba"` in `"ababa"` at $[0, 3)$ and $[2, 5)$).

Failure resolution:
- If $M = 0$ on $T^{(0)}$ ($i = 1$), the operation rejects with `match_absent`.
- If $M = 0$ on $T^{(i-1)}$ with $i > 1$, the runtime evaluates whether $m_i$ occurs in the initial transaction text $T_0$:
  If $\text{Occ}_\pi(T_0, m_i) \neq \emptyset$, the operation rejects with `sequential_match_invalid`. This diagnostic indicates that the pattern matched the original document at transaction start but is absent from intermediate buffer $T^{(i-1)}$, whether consumed by prior edits or displaced by adjacent coordinate shifts. If $m_i$ was absent in $T_0$ as well, it rejects with `match_absent`.
- If $M > 1$ and $\text{occ}_i = \bot \land \alpha_i = \bot \land \beta_i = \bot$, the operation rejects with `match_ambiguous`.

#### Step 2: Global Occurrence Index Selection
Let candidate list $C_0 = \text{Occ}_\pi(T^{(i-1)}, m_i)$.
If $\text{occ}_i \neq \bot$:
- If $1 \le \text{occ}_i \le |C_0|$, select $C_1 = \langle C_0[\text{occ}_i - 1] \rangle$.
- Otherwise, reject with `disambiguation_invalid`.
If $\text{occ}_i = \bot$, set $C_1 = C_0$.

Under singleton-selector enforcement ($\pi.\text{enforce\_singleton} = 1$), this selection step is validated even when $|C_0| = 1$. A stale selector (such as $\text{occ}_i = 2$ when only one occurrence exists) rejects cleanly with `disambiguation_invalid`.

#### Step 3: Conjunctive Anchor Filtering
For each candidate span $[s, e) \in C_1$, verify prefix and suffix containment:

$$
\text{AnchorOK}([s, e), \alpha_i, \beta_i) \iff (\alpha_i = \bot \lor \alpha_i \sqsubseteq T^{(i-1)}[0:s]) \;\land\; (\beta_i = \bot \lor \beta_i \sqsubseteq T^{(i-1)}[e:|T^{(i-1)}|])
$$

where $A \sqsubseteq B$ denotes that $A$ occurs as a substring anywhere within $B$.

The filtered candidate set is:

$$
C_2 = \{ [s, e) \in C_1 \mid \text{AnchorOK}([s, e), \alpha_i, \beta_i) \}.
$$

The operation succeeds if and only if $|C_2| = 1$, yielding resolved span $[s_i, e_i) = C_2[0]$. If $|C_2| = 0$ or $|C_2| > 1$, it rejects with `disambiguation_invalid`.

### 4.2 Class 2: Localized Guarded Code-Point Span Operations (`tx/2` span)

A guarded span operation is defined as:

$$
o_i = \text{Span}(s_i, e_i, x_i, r_i, b_i, a_i)
$$

where $0 \le s_i \le e_i \le |T^{(i-1)}|$, $x_i \in \Sigma^*$ is the expected text satisfying $|x_i| = e_i - s_i$, $r_i \in \Sigma^*$ is the replacement text, and $b_i, a_i \in \Sigma^* \cup \{\bot\}$ are optional immediate adjacency guards.

The operation succeeds on $T^{(i-1)}$ if and only if all three predicates hold:
1. **Bounds Integrity:**
   
   $$
   0 \le s_i \le e_i \le |T^{(i-1)}| \quad (\text{else } \bot \text{ with code } \texttt{span\_out\_of\_bounds}).
   $$
   
2. **Exact Substring Verification:**
   
   $$
   T^{(i-1)}[s_i : e_i] = x_i \quad (\text{else } \bot \text{ with code } \texttt{span\_expected\_text\_mismatch}, \text{check: } \texttt{expected\_text}).
   $$
   
   When $s_i = e_i$ and $x_i = \varepsilon$, this defines a zero-length insertion at code-point offset $s_i$.
3. **Immediate Adjacency Preconditions:**
   When $b_i \neq \bot$, require $s_i \ge |b_i| \land T^{(i-1)}[s_i - |b_i| : s_i] = b_i$.
   When $a_i \neq \bot$, require $e_i + |a_i| \le |T^{(i-1)}| \land T^{(i-1)}[e_i : e_i + |a_i|] = a_i$.
   Failure of either condition rejects with `span_expected_text_mismatch` (`check: expected_before` or `expected_after`).

### 4.3 Class 3: Guarded Whole-Target Replacement (`tx/3`)

A whole-target replacement operation is defined as:

$$
k = 1, \quad o_1 = \text{ReplaceAll}(r_1), \quad r_1 \in \Sigma^*.
$$

The operation unconditionally selects the full target span:

$$
[s_1, e_1) = [0, |T^{(0)}|)
$$

and maps $T^{(0)}$ directly to $r_1$, subject to the fresh admission bounds defined in Section 3.2.

### 4.4 Buffer Transformation Function

When operation $o_i$ resolves to span $[s_i, e_i)$ with replacement text $r_i$, the next intermediate buffer state is constructed via concatenation:

$$
T^{(i)} = T^{(i-1)}[0 : s_i] \,\|\, r_i \,\|\, T^{(i-1)}\bigl[e_i : |T^{(i-1)}|\bigr].
$$

The code-point length of the resulting buffer is:

$$
|T^{(i)}| = |T^{(i-1)}| - (e_i - s_i) + |r_i|.
$$

---

## 5. Core System Invariants and Formal Proofs

### Invariant 1: Localized Content Preservation Outside Resolved Spans

> **Theorem 1 (Content Preservation Outside Resolved Spans).**
> For any localized operation $o_i \in \{\text{Match}, \text{Span}\}$ resolving to span $[s_i, e_i)$ on intermediate buffer $T^{(i-1)}$ with replacement string $r_i \in \Sigma^*$, the prefix content preceding $s_i$ and the suffix content succeeding $e_i$ are preserved code-point-for-code-point:
> $$
> T^{(i)}[0 : s_i] = T^{(i-1)}[0 : s_i]
> $$
> and
> $$
> T^{(i)}\bigl[s_i + |r_i| : |T^{(i)}|\bigr] = T^{(i-1)}\bigl[e_i : |T^{(i-1)}|\bigr].
> $$

*Proof.*
By definition of the buffer transformation function (Section 4.4):

$$
T^{(i)} = A \,\|\, B \,\|\, C
$$

where $A = T^{(i-1)}[0 : s_i]$, $B = r_i$, and $C = T^{(i-1)}[e_i : |T^{(i-1)}|]$.

1. Prefix slice $T^{(i)}[0 : s_i]$ covers exactly $|A| = s_i$ code points. By monoid concatenation, this slice evaluates identically to $A = T^{(i-1)}[0 : s_i]$.
2. Replacement block $B$ occupies the interval $[s_i, s_i + |r_i|)$.
3. Suffix slice starts at offset $s_i + |r_i|$ and extends to $|T^{(i)}| = s_i + |r_i| + |C|$. The length of this slice is $|C| = |T^{(i-1)}| - e_i$. By concatenation, this slice evaluates identically to $C = T^{(i-1)}[e_i : |T^{(i-1)}|]$.

The content of the prefix and suffix substrings is identical code-point-for-code-point. When $|r_i| \neq e_i - s_i$, the absolute starting coordinate of the suffix in $T^{(i)}$ shifts by $|r_i| - (e_i - s_i)$, while its content is preserved without modification. $\blacksquare$

*Remark on Scope:* Whole-target replacement (`tx/3`) is intentionally excluded from Invariant 1, as its explicit contract replaces the entire document span $[0, |T_0|)$ under mandatory optimistic version/hash guards.

---

### Invariant 2: All-or-Nothing Per-Target Atomic State Transition

> **Theorem 2 (Per-Target Atomic Transitions).**
> Let $\mathcal{S} = (T_0, v_0, h_0)$ be the authoritative target state held under row lock:
> $$
> \texttt{SELECT * FROM cloud\_target\_files WHERE target\_file\_id = :id FOR UPDATE}.
> $$
> For any structurally valid fresh transaction submission $\mathcal{X}$:
> 1. If $\neg\text{GuardOK}(\mathcal{S}, g_v, g_h)$, if fresh admission limits fail, or if any operation $o_i \in \langle o_1, \dots, o_k \rangle$ resolves to $\bot$, the target state in `cloud_target_files` remains identically:
>    $$
>    \mathcal{S}' = \mathcal{S} = (T_0, v_0, h_0)
>    $$
>    while the rejected attempt is durably recorded in `append_only_pdcp_logs` (unless rejected prior to admission or target lock).
> 2. If and only if $\text{GuardOK}(\mathcal{S}, g_v, g_h)$ holds, admission limits pass, all $k$ operations succeed sequentially in memory ($o_i \neq \bot$ for all $1 \le i \le k$), and the database transaction commits, the target state advances atomically to:
>    $$
>    \mathcal{S}' = \bigl(T^{(k)},\; v_0 + 1,\; H(T^{(k)})\bigr)
>    $$
>    with the accepted attempt recorded in `append_only_pdcp_logs` and derived change records recorded in `append_only_manifest_ledger` in the same database transaction.

*Proof.*
The execution pipeline separates simulation from persistence:
1. When $\mathcal{X}$ arrives, the service enters a database transaction and acquires a row lock:
   
   $$
   \texttt{SELECT * FROM cloud\_target\_files WHERE target\_file\_id = :id FOR UPDATE}.
   $$
   
2. If precondition checks fail, or if during sequential in-memory simulation any $o_i$ produces $\bot$, the server issues no SQL `UPDATE` on `cloud_target_files`. Instead, it records a rejection row in `append_only_pdcp_logs` and commits the database transaction without mutating the target row. Target state remains $\mathcal{S}' = \mathcal{S}$.
3. Only when all $k$ operations produce valid intermediate buffers $T^{(1)}, \dots, T^{(k)}$ does the service execute:
   
   $$
   \texttt{UPDATE cloud\_target\_files SET current\_content = } T^{(k)}, \texttt{ version = } v_0 + 1, \texttt{ current\_hash = } H(T^{(k)})
   $$
   
   alongside the accepted attempt in `append_only_pdcp_logs` and derived change records in `append_only_manifest_ledger` within the same database transaction.
4. By PostgreSQL ACID transaction guarantees, either all updates commit or all roll back. Thus, partial intermediate states $T^{(1)}, \dots, T^{(k-1)}$ are never committed. $\blacksquare$

---

### Invariant 3: Deterministic Execution and Profile-Dispatched Replay Equivalence

> **Theorem 3 (Replay Determinism).**
> Let $T_{\text{init}} \in \Sigma^*$ be the initial document content recorded in a snapshot with hash $h_{\text{init}} = H(T_{\text{init}})$. Let $\langle (\mathcal{X}_1, p_1), (\mathcal{X}_2, p_2), \dots, (\mathcal{X}_m, p_m) \rangle$ be the ordered sequence of accepted transactions recorded in `append_only_pdcp_logs`, where each $p_j = (\tau_j, \nu_j)$ records the protocol and runtime version.
>
> Re-applying each transaction $\mathcal{X}_j$ sequentially under its recorded profile $p_j$ starting from $T_{\text{init}}$ is a pure deterministic function that yields the exact committed state:
> $$
> \text{Replay}\bigl(T_{\text{init}},\; \langle (\mathcal{X}_j, p_j) \rangle_{j=1}^m\bigr) = \bigl(T_m,\; m,\; H(T_m)\bigr).
> $$

*Proof.*
We proceed by induction on log length $m$.
- **Base Step ($m = 0$):**
  $\text{Replay}(T_{\text{init}}, \emptyset) = (T_{\text{init}}, 0, H(T_{\text{init}}))$. This equals initial state $(T_0, 0, h_0)$ with $h_0 = H(T_{\text{init}})$.
- **Inductive Step:**
  Assume the theorem holds for $m - 1$ accepted transactions, yielding state $(T_{m-1}, m-1, H(T_{m-1}))$.
  Transaction $\mathcal{X}_m$ was accepted in historical execution, which implies:
  
  $$
  \text{GuardOK}\bigl((T_{m-1}, m-1, H(T_{m-1})),\; g_v^{(m)},\; g_h^{(m)}\bigr) = \text{true}.
  $$
  
  Because the applier is a pure mathematical function of $(T_{m-1}, \mathcal{X}_m, \pi_m)$ with $\pi_m = \text{ResolveProfile}(\nu_m)$:
  1. LF canonicalization is deterministic and idempotent.
  2. String slicing and exact code-point index lookups in $\Sigma^*$ are deterministic.
  3. Occurrence list $\text{Occ}_{\pi_m}(T_{m-1}, m_i)$ depends strictly on static string values under profile $\pi_m$.
  4. Concatenation $T^{(i-1)}[0:s_i] \,\|\, r_i \,\|\, T^{(i-1)}[e_i:]$ is deterministic.
  Therefore, the final replayed buffer $T^{(k)}$ produced by $\mathcal{X}_m$ evaluates to the exact string $T_m$.
  The version counter advances to $(m - 1) + 1 = m$, and the recomputed digest evaluates to $H(T_m) = \text{SHA256}_{\text{hex}}(\text{UTF8}(T_m))$.
By induction, replay reproduces the exact materialized state for all $m \ge 0$. $\blacksquare$

---

### Invariant 4: Request-Key Idempotency and State Monotonicity

> **Theorem 4 (Strict Request-Key Idempotency and Monotonicity).**
> Let $F$ denote a target file identifier and $q \in \Sigma^+$ denote a non-null client request identifier. Let $\mathcal{R}(F, q)$ denote the set of transaction submissions evaluated for target $F$ with key $q$.
> 1. At most one submission in $\mathcal{R}(F, q)$ is ever executed against the document applier.
> 2. Any subsequent submission $\mathcal{X}' \in \mathcal{R}(F, q)$ whose request fingerprint matches the recorded fingerprint returns the exact recorded terminal outcome with response flag:
>    $$
>    \texttt{deduplicated: true}
>    $$
>    without re-evaluating operations, inserting a new attempt log, or mutating target state. The version counter $v_0$ is not incremented.
> 3. Any subsequent submission $\mathcal{X}'' \in \mathcal{R}(F, q)$ whose request fingerprint diverges from the recorded fingerprint is rejected with:
>    $$
>    \texttt{failure\_reason: "context\_invalid"},\; \texttt{diagnostic.code: "request\_key\_conflict"}
>    $$
>    Target state is unchanged, and the conflict attempt is audited under a NULL key to preserve the original binding.
> 4. Version increments occur if and only if a fresh, non-duplicate transaction is accepted and committed ($v \leftarrow v_0 + 1$); deduplicated retries and rejections never increment the version.

*Proof.*
1. Under the row lock acquired on target $F$, the service queries `append_only_pdcp_logs` for an existing record matching $(F, q)$.
2. If no record exists, the transaction is fresh. The key $q$ is bound to the attempt record inserted during commit. By the unique constraint on $(F, q)$ across active attempt records, at most one attempt can commit with key $(F, q)$.
3. If an existing record is found, the service compares the SHA-256 fingerprint of the incoming request payload with the persisted fingerprint:
   - If fingerprints match, the server reconstructs the response directly from the persisted record, sets `deduplicated = true`, and returns immediately. Target state $\mathcal{S}$ and version $v_0$ are unchanged, and no new log entry is created.
   - If fingerprints differ, a client is attempting to reuse an existing idempotency key with conflicting payload data. The transaction aborts with `request_key_conflict`. The rejection is logged with `client_request_id = NULL` to ensure the original $(F, q)$ binding is preserved. Target state $\mathcal{S}$ and version $v_0$ are unchanged. $\blacksquare$

---

## 6. Implementation Traceability and Verification Matrix

The formal constructs defined in this paper correspond directly to verified software modules within the PatchDIFF implementation:

| Formal Construct | Implementation Module | Automated Test Coverage |
| :--- | :--- | :--- |
| **String Domain & Canonicalization ($\Sigma$, LF)** | `backend/app/core/canonicalization.py:canonicalize_text` | `backend/tests/unit/test_canonicalization.py` |
| **Text Safety & NUL/Surrogate Rejection** | `backend/app/core/input_text.py:is_persistable_text` | `backend/tests/unit/test_invalid_input_unicode.py` |
| **Cryptographic Digest Function ($H$)** | `backend/app/core/hashing.py:canonical_sha256` | `backend/tests/unit/test_hashing.py` |
| **State Space ($\mathcal{S} = (T_0, v_0, h_0)$)** | `backend/app/storage/models.py:CloudTargetFiles` | `backend/tests/integration/test_pdcp_submit_flow.py` |
| **Precondition Guard & Idempotency** | `backend/app/services/pdcp_service.py:submit_pdcp_transaction` | `backend/tests/integration/test_typed_submit_flow.py` |
| **Exact Occurrence Enumeration ($\text{Occ}_\pi$)** | `backend/app/pdcp/matcher.py:find_exact_occurrences` | `backend/tests/unit/test_matcher.py` |
| **Disambiguation Resolution** | `backend/app/pdcp/disambiguation.py:resolve_disambiguation` | `backend/tests/unit/test_disambiguation.py` |
| **Class 1 Applier (`tx/1` exact match)** | `backend/app/pdcp/typed.py:parse_typed_record`, `backend/app/pdcp/applier.py:apply_pdcp_transaction` | `backend/tests/unit/test_typed_transaction.py`, `backend/tests/unit/test_transaction_applier.py` |
| **Class 2 Applier (`tx/2` guarded span)** | `backend/app/pdcp/operations.py:parse_operations_record` | `backend/tests/unit/test_pass_a_operations.py` |
| **Class 3 Applier (`tx/3` whole replacement)** | `backend/app/pdcp/replacement.py:parse_replacement_record`, `replacement_size_evidence` | `backend/tests/unit/test_pass_a_operations.py` |
| **Invariant 1 (Content Preservation)** | `backend/app/pdcp/applier.py` | `backend/tests/unit/test_transaction_applier.py`, `backend/tests/verification/offline_eval.py` |
| **Invariant 2 (All-or-Nothing Atomicity)** | `backend/app/services/pdcp_service.py:submit_pdcp_transaction` | `backend/tests/integration/test_typed_submit_flow.py` |
| **Invariant 3 (Replay Equivalence)** | `backend/app/services/replay_service.py:replay_target` | `backend/tests/integration/test_replay.py` |
| **Invariant 4 (Request-Key Idempotency)** | `backend/app/services/pdcp_service.py:submit_pdcp_transaction` | `backend/tests/integration/test_conflict_audit_live.py`, `backend/tests/unit/test_conflict_audit.py` |

---

## References

1. **Model Context Protocol Specification:** Anthropic, *Model Context Protocol Specification (JSON-RPC 2.0 Transport & Tool Calling)*, `https://modelcontextprotocol.io/`.
2. **IETF RFC 6902:** P. Bryan and M. Nottingham, *JavaScript Object Notation (JSON) Patch*, RFC 6902, April 2013.
3. **Unicode Standard Annex #29:** M. Davis, *Unicode Text Segmentation (Extended Grapheme Clusters)*, Unicode Consortium.
4. **Optimistic Concurrency Control:** H. T. Kung and J. T. Robinson, *"On Optimistic Methods for Concurrency Control,"* ACM Transactions on Database Systems (TODS), 6(2):213-226, 1981.
5. **PatchDIFF Companion Papers & Normative Specifications:**
   - [AGENTS.md](https://github.com/paragon-ux/Patch-DIFF/blob/main/AGENTS.md): Locked repository invariants and precedence order.
   - [Core Runtime Specification](../spec/core-runtime.md): Deterministic applier, validation stages, and runtime profile definitions.
   - [Data Model](../spec/data-model.md): PostgreSQL schema, constraints, and migrations.
   - [Transaction Formats](../spec/transaction-formats.md): Declarative JSON transaction specifications (`patchdiff-tx/1`, `patchdiff-tx/2`, `patchdiff-tx/3`).
   - [MCP Tool Contracts](../spec/mcp-tools.md): Tool definitions, schemas, and byte budgets.
   - [Profiles](../spec/profiles/index.md): Profile selection, startup contracts, and tool sets.
   - [Concept Paper v6](concept-paper-v6.md): Conceptual systems architecture, comparative paradigm analysis, and empirical evaluation.
   - [Modernization Architecture](modernization-architecture.md): Systems architecture, profile boundaries, and technical reconciliation.
   - [Product Change Record](product-change-record.md): Product change record, formats, and compatibility history.
