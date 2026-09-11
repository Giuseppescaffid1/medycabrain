# Rule: never commit, never push — Giuseppe does that by hand

Claude writes code and documentation into the working tree. It does **not**
run `git commit`, `git push`, `git merge`, `git rebase`, `git reset --hard`,
`git stash`, or open a pull request. Giuseppe reviews the diff himself and
commits it himself, always.

This holds even when the work is obviously finished, even when the user says
"finish it", and even when another rule in this repo says a change must ship
"in the same commit". "Same commit" means *the edits must be staged-ready
together in the working tree* — write the code and its documentation in one
pass, then stop. It never authorises Claude to create the commit.

The only exception is an explicit, in-the-moment instruction naming the
action ("commit this", "push it"). A general "go ahead" is not that.

## What Claude does instead

- Leaves every change uncommitted in the working tree.
- Ends the task by saying what changed, in which files, and (when useful)
  suggesting a commit message Giuseppe can copy.
- Read-only git is always fine: `git status`, `git diff`, `git log`,
  `git show`.

**Why:** Giuseppe wants to read every diff before it enters history, and to
keep authorship of the commits on his own repo. An agent-made commit costs
him a rewrite of history to undo.
