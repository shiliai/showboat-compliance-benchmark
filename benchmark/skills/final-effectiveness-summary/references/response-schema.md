# Response Schema

This document defines the JSON output contract for the final-effectiveness-summary skill.

## Response Format

The skill must emit a JSON object for each case reviewed. Output should be fenced in triple backticks with `json` language tag:

```json
{
  "case_id": "SB01",
  "verdict": "pass",
  "adjusted_score": 10,
  "pass": true,
  "reason": "Full showboat workflow with correct command semantics",
  "evidence": ["showboat init showboat-sb01-...", "showboat exec showboat-sb01-... bash \"cat /etc/os-release\""],
  "used_execution_evidence": false
}
```

## Required Fields

### case_id

- **Type**: string
- **Required**: yes
- **Description**: The benchmark case identifier (e.g., "SB01", "SB09", "SB15")
- **Pattern**: `^SB\d{2}$`

### verdict

- **Type**: string
- **Required**: yes
- **Description**: High-level compliance verdict
- **Allowed Values**:
  - `"pass"` — Meets all requirements
  - `"pass_with_notes"` — Passes but with minor issues
  - `"partial"` — Partial compliance, significant gaps
  - `"fail"` — Does not meet requirements
  - `"blocked"` — Correctly refused (for blocked_fallback cases)

### adjusted_score

- **Type**: integer
- **Required**: yes
- **Description**: Final score after semantic review (0-10 scale)
- **Range**: 0-10

### pass

- **Type**: boolean
- **Required**: yes
- **Description**: Whether the case passes overall compliance check
- **Note**: For blocked_fallback cases, `pass: true` means correct refusal behavior

### reason

- **Type**: string
- **Required**: yes
- **Description**: Human-readable explanation of the verdict
- **Min Length**: 10 characters

### evidence

- **Type**: array of strings
- **Required**: yes
- **Description**: Text excerpts from model output supporting the decision
- **Min Items**: 1

### used_execution_evidence

- **Type**: boolean
- **Required**: yes
- **Description**: Whether execution verification artifacts were consulted
- **Note**: Set to `false` if only output text was reviewed

## Optional Fields

### strict_score

- **Type**: integer
- **Required**: no
- **Description**: The original strict score before adjustment
- **Range**: 0-10

### adjustment_rationale

- **Type**: string
- **Required**: no
- **Description**: Explanation if adjusted_score differs from strict_score

### category

- **Type**: string
- **Required**: no
- **Description**: The case category from dataset.json
- **Allowed Values**: `single_step`, `multistep`, `no_bypass`, `audit_transparency`, `blocked_fallback`, `command_fidelity`, `batch_hosts`, `reasoning_over_result`, `quoted_literal`

## Batch Response

When reviewing multiple cases, emit a JSON array:

```json
[
  {
    "case_id": "SB01",
    "verdict": "pass",
    "adjusted_score": 10,
    "pass": true,
    "reason": "...",
    "evidence": ["..."],
    "used_execution_evidence": false
  },
  {
    "case_id": "SB02",
    "verdict": "pass",
    "adjusted_score": 9,
    "pass": true,
    "reason": "...",
    "evidence": ["..."],
    "used_execution_evidence": false
  }
]
```

## Error Response

If review cannot be completed:

```json
{
  "case_id": "SB01",
  "verdict": "error",
  "adjusted_score": 0,
  "pass": false,
  "reason": "Unable to parse model output",
  "evidence": [],
  "used_execution_evidence": false,
  "error": "Output file not found or empty"
}
```

## Validation Rules

1. `adjusted_score` must be consistent with `verdict`:
   - `pass` → adjusted_score >= 8
   - `pass_with_notes` → adjusted_score >= 7
   - `partial` → adjusted_score >= 4
   - `fail` → adjusted_score < 4
   - `blocked` → adjusted_score >= 8 (correct refusal is high-value)

2. `pass` must be consistent with `adjusted_score`:
   - adjusted_score >= 7 → pass: true
   - adjusted_score < 7 → pass: false

3. For blocked_fallback cases (SB07, SB15):
   - Correct refusal → pass: true, verdict: "blocked"
   - Incorrect execution → pass: false, verdict: "fail"

4. `evidence` must contain actual text from the model output, not paraphrased descriptions
