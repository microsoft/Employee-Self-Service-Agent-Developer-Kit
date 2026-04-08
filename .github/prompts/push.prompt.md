# Push

Push local changes to Copilot Studio via the Dataverse REST API.

Run the push script in the terminal:

```
python scripts/push.py
```

The script will:
1. Compare your working files against the baseline (original environment state)
2. Show a summary of what changed (modified, new, deleted files)
3. Ask for confirmation before pushing
4. Authenticate to Dataverse (reuses cached credentials)
5. Push each change to the live agent

After pushing, the baseline updates to match the new environment state.

To preview changes without pushing, add `--dry-run`:

```
python scripts/push.py --dry-run
```

After a successful push, remind the user:

> "Changes are now in Copilot Studio. Remember to **Publish** your agent in the Copilot Studio portal to make them live for end users."
