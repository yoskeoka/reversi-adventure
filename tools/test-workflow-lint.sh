#!/bin/sh
set -eu

root=$(git rev-parse --show-toplevel)
linter="$root/tools/workflow-lint.sh"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/workflow-lint-test.XXXXXX")
trap 'rm -rf "$tmp"' 0 1 2 15

make_fixture() {
    name=$1
    plan_body=$2
    dir="$tmp/$name"

    mkdir -p "$dir/docs/exec-plan/todo" "$dir/docs/issues" "$dir/tools"
    cp "$linter" "$dir/tools/workflow-lint.sh"
    chmod +x "$dir/tools/workflow-lint.sh"
    printf '%s\n' "$plan_body" > "$dir/docs/exec-plan/todo/0001-$name.md"
    printf '%s\n' '# tracked local issue' > "$dir/docs/issues/0001-$name.md"
    git -C "$dir" init -q -b main
    git -C "$dir" config user.email workflow-lint@example.invalid
    git -C "$dir" config user.name workflow-lint-test
    git -C "$dir" add .
    git -C "$dir" commit -qm base
    git -C "$dir" remote add origin https://github.com/example/workflow-lint-fixture.git
    git -C "$dir" update-ref refs/remotes/origin/main HEAD
    git -C "$dir" switch -q -c "feat/$name"
    printf '%s\n' "$dir"
}

assert_contains() {
    needle=$1
    haystack=$2
    if ! grep -qF "$needle" "$haystack"; then
        echo "expected output to contain: $needle" >&2
        cat "$haystack" >&2
        exit 1
    fi
}

assert_not_contains() {
    needle=$1
    haystack=$2
    if grep -qF "$needle" "$haystack"; then
        echo "expected output not to contain: $needle" >&2
        cat "$haystack" >&2
        exit 1
    fi
}

assert_no_warnings() {
    assert_not_contains '[WARN:' "$1"
}

run_linter() {
    dir=$1
    output=$2
    shift 2

    if ! (cd "$dir" && ./tools/workflow-lint.sh "$@") >"$output" 2>&1; then
        echo "workflow-lint exited non-zero for fixture $dir" >&2
        cat "$output" >&2
        (cd "$dir" && bash -x ./tools/workflow-lint.sh "$@") >&2 || true
        exit 1
    fi
}

# An active execution remains valid before closeout.
active_dir=$(make_fixture active-plan '# active plan')
run_linter "$active_dir" "$tmp/active.out" --mode=pre-push
assert_not_contains 'Missing exec-plan' "$tmp/active.out"
assert_no_warnings "$tmp/active.out"

# Deleting a plan and its linked local issue is a compliant closeout.
local_dir=$(make_fixture local-closeout 'Addresses: docs/issues/0001-local-closeout.md')
git -C "$local_dir" rm -- docs/exec-plan/todo/0001-local-closeout.md docs/issues/0001-local-closeout.md >/dev/null
git -C "$local_dir" commit -qm closeout
run_linter "$local_dir" "$tmp/local.out" --mode=pre-push
assert_not_contains 'Missing exec-plan' "$tmp/local.out"
assert_not_contains 'but this branch does not delete it' "$tmp/local.out"
assert_no_warnings "$tmp/local.out"

# A plan without links may be deleted on its own.
plan_only_dir=$(make_fixture plan-only '# no linked issue')
git -C "$plan_only_dir" rm -- docs/exec-plan/todo/0001-plan-only.md >/dev/null
git -C "$plan_only_dir" commit -qm closeout
run_linter "$plan_only_dir" "$tmp/plan-only.out" --mode=pre-push
assert_not_contains 'Missing exec-plan' "$tmp/plan-only.out"
assert_no_warnings "$tmp/plan-only.out"

# Omitting a linked local issue remains a fixable warning.
missing_local_dir=$(make_fixture missing-local 'Addresses: docs/issues/0001-missing-local.md')
git -C "$missing_local_dir" rm -- docs/exec-plan/todo/0001-missing-local.md >/dev/null
git -C "$missing_local_dir" commit -qm closeout
run_linter "$missing_local_dir" "$tmp/missing-local.out" --mode=pre-push
assert_contains "Deleted exec-plan 'docs/exec-plan/todo/0001-missing-local.md' links local issue 'docs/issues/0001-missing-local.md' but this branch does not delete it" "$tmp/missing-local.out"

# External links retain CI closing-keyword enforcement after the plan is deleted.
external_dir=$(make_fixture external-closeout 'Addresses: https://github.com/example/workflow-lint-fixture/issues/42')
git -C "$external_dir" rm -- docs/exec-plan/todo/0001-external-closeout.md >/dev/null
git -C "$external_dir" commit -qm closeout
run_linter "$external_dir" "$tmp/external-ok.out" --mode=ci --pr-body='Closes #42'
assert_not_contains 'does not include a matching closing keyword' "$tmp/external-ok.out"
assert_no_warnings "$tmp/external-ok.out"
run_linter "$external_dir" "$tmp/external-missing.out" --mode=ci --pr-body=''
assert_contains "Deleted exec-plan 'docs/exec-plan/todo/0001-external-closeout.md' links external GitHub issue 'https://github.com/example/workflow-lint-fixture/issues/42' but the PR body does not include a matching closing keyword" "$tmp/external-missing.out"

# Historical archives are rejected as active workflow records.
archive_dir=$(make_fixture historical-archive '# active plan')
mkdir -p "$archive_dir/docs/exec-plan/done" "$archive_dir/docs/issues/done"
run_linter "$archive_dir" "$tmp/archive.out" --mode=pre-push
assert_contains "Historical workflow archive 'docs/exec-plan/done' remains" "$tmp/archive.out"
assert_contains "Historical workflow archive 'docs/issues/done' remains" "$tmp/archive.out"

echo "workflow-lint lifecycle fixtures passed"
