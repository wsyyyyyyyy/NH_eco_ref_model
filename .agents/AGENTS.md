# Git Workflow Rules
- **DO NOT force push to main:** Never use `git push --force` or overwrite the commit history on the `main` or `master` branch.
- **Use Pull Requests:** When committing changes, always push to a new feature branch (e.g., `git push -u origin branch-name`) and instruct the user to merge the changes via a Pull Request (Compare & pull request) on GitHub. This preserves the original repository's commit history.
