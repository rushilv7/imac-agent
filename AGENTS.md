# iMac Agent Operating Rules

This repository is the operational workspace for the Toronto Ubuntu iMac server.

## Default behaviour

- Inspect first.
- Prefer read-only diagnostics.
- Explain problems before changing anything.
- Never expose secrets, API keys, SSH private keys, or environment files.
- Never delete files, modify firewall rules, install packages, reboot, shut down, or change networking without explicit approval.
- Never use unrestricted sudo automatically.
- Never modify backup drives.

## Server

- Host: rushil-imac
- Primary user: rushil
- Remote access: Tailscale + OpenSSH
- Project root: /home/rushil/projects/imac-agent

## Approved read-only scripts

- scripts/server-status.sh
- scripts/check-services.sh
- scripts/network-status.sh
- scripts/recent-errors.sh
- scripts/project-status.sh

## Controlled write scripts

- scripts/update-project.sh
- scripts/restart-service.sh

Before executing a controlled write action, summarize:
1. What will change
2. Why it is necessary
3. What command will run
4. How to recover if it fails

## Safety

Do not:
- expose SSH publicly
- alter Tailscale configuration without approval
- disable the firewall
- modify /etc without approval
- modify disks or partitions
- run destructive commands
- push code or deploy services without approval

When uncertain, stop and ask.
