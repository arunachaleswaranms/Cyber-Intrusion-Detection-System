# v2.1.0 maintainer release handoff

Publication is complete. Phases 1–5 are implemented, reviewed and merged;
independent Phase 5 review found no blocking issues within the
[documented scope](release-readiness-v2.1.md).

[v2.1.0](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/releases/tag/v2.1.0) was published as a stable GitHub Release on
2026-10-04 at `ed2e38a9014ee52756276bb0707d0de09ea3df35`. Release closure
[PR #8](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/pull/8) is merged; all five closure
post-merge jobs passed in [run 37207887388](https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System/actions/runs/37207887388).
The project is paused for maintenance; no next-version implementation is authorized.
The annotated tagger is `Arunachaleswaran M S <arunachaleswaranms@gmail.com>`.
The historical closure branch was `release/v2.1.0-closure`.
No container image was published. Any possible future v3.0 milestone requires
fresh design and explicit approval.

No known failing technical acceptance check remains within the tested scope.
Broader browser/theme/responsive coverage, other image architectures and original
trusted-artifact integration on amd64 remain unqualified. The reviewer lacked
Docker and used CI logs; original-model/browser evidence was not independently
repeated. No formal GitHub approval was submitted.

## Historical guarded publication procedure — completed for v2.1.0

**Reference only: this procedure was already completed for v2.1.0. Do not rerun
it, recreate the Release or move/recreate the tag.** The existing tag and stable
Release are the publication record.

The following is the preserved pre-publication procedure. It required separate
publication authorization and a merged closure PR. These commands
resolve the closure PR's merge, fetch actual current main and verify that it
contains the closure merge. They select that current main commit, require its
five-job push CI to have passed, read the final notes from that commit, and
refuse any existing local/remote `v2.1.0` tag or GitHub Release (including drafts).
They never use the pre-closure Phase 5 SHA as the release target. If main advances
again during preparation, the script stops so the new target can be reviewed.
Review any intervening main changes before authorizing publication.

```bash
bash <<'BASH'
set -euo pipefail
repo=arunachaleswaranms/Cyber-Intrusion-Detection-System
tag=v2.1.0
branch=release/v2.1.0-closure
expected_origin=https://github.com/arunachaleswaranms/Cyber-Intrusion-Detection-System.git
[ "$(git remote get-url origin)" = "$expected_origin" ]
[ -z "$(git status --porcelain)" ]
[ "$(git var GIT_AUTHOR_IDENT | cut -d '>' -f 1)>" = \
  'Arunachaleswaran M S <arunachaleswaranms@gmail.com>' ]
[ "$(git var GIT_COMMITTER_IDENT | cut -d '>' -f 1)>" = \
  'Arunachaleswaran M S <arunachaleswaranms@gmail.com>' ]

pr_state=$(gh pr view "$branch" --repo "$repo" --json state --jq .state)
pr_base=$(gh pr view "$branch" --repo "$repo" --json baseRefName --jq .baseRefName)
closure_merge=$(gh pr view "$branch" --repo "$repo" --json mergeCommit --jq .mergeCommit.oid)
[ "$pr_state" = MERGED ]
[ "$pr_base" = main ]
[ -n "$closure_merge" ]
git fetch origin main --tags
target=$(git rev-parse 'refs/remotes/origin/main^{commit}')
git merge-base --is-ancestor "$closure_merge" "$target"
git log --oneline "$closure_merge..$target"
printf 'Release target: %s\n' "$target"

assert_absent() {
  if git show-ref --verify --quiet "refs/tags/$tag"; then
    printf 'Refusing existing local tag %s\n' "$tag" >&2
    return 1
  fi
  remote_tag=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")
  [ -z "$remote_tag" ] || { printf 'Refusing existing remote tag\n' >&2; return 1; }
  releases=$(gh api --paginate "repos/$repo/releases?per_page=100" \
    --jq '.[] | select(.tag_name == "v2.1.0") | .id')
  [ -z "$releases" ] || { printf 'Refusing existing Release, including draft\n' >&2; return 1; }
}
assert_absent

run_id=$(gh run list --repo "$repo" --branch main --event push \
  --workflow test.yml --commit "$target" --limit 20 \
  --json databaseId --jq '.[0].databaseId // empty')
[ -n "$run_id" ]
ci_ok=$(gh run view "$run_id" --repo "$repo" \
  --json headSha,status,conclusion,jobs \
  --jq ".headSha == \"$target\" and .status == \"completed\" and .conclusion == \"success\" and ([.jobs[].name] | sort) == ([\"test\", \"reproduction-environment\", \"workbench-phase-1\", \"dashboard-phase-2\", \"container-packaging\"] | sort) and all(.jobs[]; .status == \"completed\" and .conclusion == \"success\")")
[ "$ci_ok" = true ]
gh run view "$run_id" --repo "$repo" --json url,conclusion

notes=$(mktemp /tmp/cids-v2.1.0-notes.XXXXXX)
trap 'rm -f "$notes"' EXIT
git show "$target:docs/release-notes-v2.1.0.md" > "$notes"
[ -s "$notes" ]
cat "$notes"
# Confirm that main has not advanced while preparing the release.
remote_main=$(git ls-remote origin refs/heads/main | cut -f 1)
[ "$remote_main" = "$target" ]
assert_absent

git tag -a "$tag" "$target" -m 'CIDS v2.1.0 analyst workbench'
[ "$(git rev-parse "$tag^{commit}")" = "$target" ]
git push origin "refs/tags/$tag"
gh release create "$tag" --repo "$repo" --verify-tag --target "$target" \
  --title 'CIDS v2.1.0' --notes-file "$notes"
BASH
```

If publication fails after the tag push, preserve that tag and inspect the remote
state. Do not move/delete an existing tag or blindly rerun this script; it refuses
existing tags by design. No image push is included.

Release closure and publication are complete. The project is paused for
maintenance; no next-version implementation is authorized.
