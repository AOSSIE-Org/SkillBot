# The repositories Skill Bot answers questions about. Add one entry per repository.
#
#   "<RepoName>": {
#       # Repository to copy docs from. Add /tree/<branch> to use a branch other than main.
#       "url": "https://github.com/<owner>/<repo>",
#       # One line, shown when the bot asks which project a question is about.
#       "description": "<what the project is>",
#       # Optional. Words contributors use for this project; its name already matches.
#       "keywords": ["<word>", "<phrase>"],
#       # Optional. Files and folders to copy into repos/<RepoName>/. A path ending in .md is
#       # one file; any other path is a folder, and every .md file inside it is copied.
#       # Defaults to ["README.md"].
#       "docs": ["README.md", "CONTRIBUTING.md", "docs/"],
#   },
#
# Copied docs are not all sent to the model: for each question the bot picks only the files
# whose names match it (see load_repo_context() in repo_router.py), so a longer "docs" list
# does not slow the local model down.
#
# A shared skills repository is just another entry, for example:
#
#   "Skills": {
#       "url": "https://github.com/<owner>/skills",
#       "description": "Organization-wide rules: contributor onboarding, AI usage policy",
#       "keywords": ["onboarding", "ai policy"],
#       "docs": ["contributor-onboarding/", "ai-policy/"],
#   },
#
# Keep the list to the repositories contributors actually ask about: every entry is one more
# choice for the local model when it has to guess which repository a question is about.
REPO_METADATA = {
    "Example-Project": {
        "url": "https://github.com/your-org/example-project",
        "description": "Replace this entry with your own repositories",
        "keywords": ["example"],
        "docs": ["README.md", "CONTRIBUTING.md", "docs/"],
    },
}
