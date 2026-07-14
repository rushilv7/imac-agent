# iMac Server Recovery

## Base server

1. Install Ubuntu.
2. Connect to the internet.
3. Install Git.
4. Configure the iMac GitHub SSH key.
5. Clone this repository:

   git clone git@github.com:rushilv7/imac-agent.git

6. Enter the repository:

   cd imac-agent

7. Run:

   ./bootstrap.sh

## Restore Tailscale

Install Tailscale and authenticate the iMac into the correct tailnet.

Verify:

    tailscale status

## Restore Hermes

Install Hermes as the `rushil` user.

Restore model configuration and API credentials manually.

Never commit secrets to this repository.

## Validate

Run:

    ./scripts/server-status.sh
    ./scripts/check-services.sh
    ./scripts/network-status.sh
    ./scripts/recent-errors.sh

Then reboot and confirm SSH over Tailscale works again.
