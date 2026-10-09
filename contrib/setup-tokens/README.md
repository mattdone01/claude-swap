# Setup-token accounts across several machines

Helper scripts for running the same cswap accounts on more than one machine.

## Why setup-tokens

A normal `/login` credential rotates: every refresh issues a new refresh token and
invalidates the previous one. If two machines hold the same account, whichever
refreshes first kills the other's copy, and the other machine reports
"re-login needed". Two `cswap auto` daemons with the same strategy and the same
usage data also tend to pick the same account at the same moment, which makes
this happen several times a day.

A `claude setup-token` credential never rotates (it lasts about a year), so the
same token can be live on several machines at once. cswap reads its usage from
the `anthropic-ratelimit-unified-*` headers of a 1-token request, because the
usage endpoint refuses setup-tokens.

Trade-offs:

- The headers report the 5-hour and 7-day windows only, not per-model weekly
  windows. If `autoswitch.model` is set, cswap logs a config warning that the
  model matches no account's windows.
- A setup-token carries only the `user:inference` scope. Claude Code features
  that need more scope (claude.ai connectors, cloud sessions, plugin sync) are
  unavailable on these logins.

## Scripts

| Script | Purpose |
| --- | --- |
| `cswap-settoken <slot> <email>` | Prompt for a token (hidden), check it (108 chars, one prefix, authenticates), register it in the slot here and on every peer, back it up |
| `cswap-settokens-batch <file>` | Run `cswap-settoken` for every `email token` line (`email: token` also works); slot looked up by email; file shredded afterwards |
| `cswap-restore-tokens` | Re-import every backed-up token on this machine (after `cswap purge`, a wiped data dir, or a fresh install) |
| `cswap-check-headerusage` | Exit non-zero with a warning if the installed cswap lacks setup-token header usage |
| `claude-swap-auto-headerusage-check.conf` | systemd `--user` drop-in that runs the check before the `cswap auto` service starts |

Backups are plain JSON from `cswap export` in `~/.config/cswap-backup/slot-N.json`
(directory 700, files 600). They are outside cswap's data directory, so a rebuild
or `cswap purge` does not touch them.

## Setup

On each machine:

```bash
install -m 700 cswap-settoken cswap-settokens-batch cswap-restore-tokens ~/.local/bin/
install -m 755 cswap-check-headerusage ~/.local/bin/
mkdir -p ~/.config/cswap-backup && chmod 700 ~/.config/cswap-backup
echo "user@other-machine" >> ~/.config/cswap-backup/peers   # one SSH target per line
```

Peers can also be given as `CSWAP_PEERS="host1 host2"`. Each peer needs cswap,
`jq`, and non-interactive SSH access from this machine.

Optional rebuild guard:

```bash
mkdir -p ~/.config/systemd/user/claude-swap-auto.service.d
cp claude-swap-auto-headerusage-check.conf \
   ~/.config/systemd/user/claude-swap-auto.service.d/headerusage-check.conf
systemctl --user daemon-reload && systemctl --user restart claude-swap-auto
```

## Converting accounts

```bash
claude setup-token                 # log in as the account in the browser
cswap-settoken 3 user@example.com  # paste the token at the hidden prompt
```

For many accounts, put `email token` lines in a file and run
`cswap-settokens-batch tokens.txt`. Afterwards switch the live login onto its
token with `cswap --switch-to <active slot> --force`, so cswap does not write the
old rotating credential back into the slot on its next switch.
