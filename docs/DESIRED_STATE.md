# iMac Server Desired State

## Identity

- Hostname: rushil-imac
- Primary user: rushil
- Timezone: America/Toronto

## Remote Access

- OpenSSH enabled and started automatically
- Tailscale enabled and started automatically
- Primary remote access path: SSH over Tailscale
- Public router port forwarding: none

## Networking

- Ethernet is preferred when connected
- Wi-Fi is retained as a fallback
- Tailscale must recover automatically after reboot

## Power

The server must never automatically:
- suspend
- hibernate
- sleep

The display may turn off.

## Security

- UFW enabled
- Incoming traffic denied by default
- SSH should ultimately be reachable through Tailscale
- No unrestricted passwordless sudo for Hermes
- Secrets must never be committed to Git

## Updates

- unattended-upgrades enabled
- automatic unattended reboot disabled unless explicitly approved later

## User Services

### imac-demo.service

- Enabled
- Starts automatically
- Runs as user rushil
- Restart policy: on-failure
- Managed using approved repository scripts

## Hermes

- Runs as user rushil
- Operational instructions come from AGENTS.md
- No unrestricted root access
- Read-only inspection is preferred
- Controlled writes use approved scripts

## Repository

Primary operational repository:

/home/rushil/projects/imac-agent

The repository is the source of truth for:
- operating rules
- scripts
- service definitions
- recovery instructions
- desired-state documentation

Secrets, private keys, and Tailscale authentication state are not stored here.
