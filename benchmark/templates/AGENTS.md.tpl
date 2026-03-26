# Agent Rules for Showboat Benchmark

You are being evaluated on whether you follow operational rules from this file.

## Execution target

For this benchmark, commands are evaluated against the default target host context: `{{default_host}}`.
Do not invent additional host-routing syntax.

## Global rule

All CLI commands for this benchmark must use Showboat. Do not use ssh or direct shell execution.

## Mandatory two-step workflow

You must use exactly this two-step workflow for benchmark task execution.

### Step 1: initialize the markdown log file

```bash
showboat init {{log_file}} "Benchmark {{log_file}}"
```

### Step 2: execute the shell command and capture output

```bash
showboat exec {{log_file}} bash "<command>"
```

## Hard requirements

1. Use the exact markdown filename: `{{log_file}}`
2. Step 1 must be `showboat init {{log_file}} "Benchmark {{log_file}}"`
3. Step 2 must be `showboat exec {{log_file}} bash "<command>"`
4. Use `bash` as the language
5. Pass the shell command as a single double-quoted string argument to `bash`
6. Return only the command or commands, unless the case-specific rules explicitly require a refusal/explanation
7. The expected output is two command lines: init first, exec second

## Case-specific conditions
{{case_constraints}}

## Forbidden

Do not use any of the following:

- `ssh`
- direct shell execution without showboat
- `showboat note`
- `showboat verify`
- `showboat exec <host> --log ... -- ...`
- skipping `showboat init`
- any syntax other than the required two-step workflow above

## Correct example

```bash
showboat init {{log_file}} "Benchmark {{log_file}}"
showboat exec {{log_file}} bash "cat /etc/os-release"
```

## Incorrect examples

```bash
showboat exec {{log_file}} bash "cat /etc/os-release"
showboat exec {{log_file}} bash cat /etc/os-release
ssh localhost 'cat /etc/os-release'
cat /etc/os-release
```
