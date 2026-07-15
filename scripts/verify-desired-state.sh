#!/usr/bin/env bash
set -u

PASS=0
FAIL=0

check() {
  local name="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

check "hostname is rushil-imac" \
  test "$(hostname)" = "rushil-imac"

check "timezone is America/Toronto" \
  test "$(timedatectl show -p Timezone --value)" = "America/Toronto"

check "SSH active" \
  systemctl is-active --quiet ssh

check "SSH enabled" \
  systemctl is-enabled --quiet ssh

check "Tailscale active" \
  systemctl is-active --quiet tailscaled

check "Tailscale enabled" \
  systemctl is-enabled --quiet tailscaled

check "unattended-upgrades active" \
  systemctl is-active --quiet unattended-upgrades

check "user lingering enabled" \
  test "$(loginctl show-user "$USER" -p Linger --value)" = "yes"

check "sleep target masked" \
  test "$(systemctl is-enabled sleep.target 2>/dev/null)" = "masked"

check "suspend target masked" \
  test "$(systemctl is-enabled suspend.target 2>/dev/null)" = "masked"

check "imac-demo active" \
  systemctl --user is-active --quiet imac-demo.service

check "imac-demo enabled" \
  systemctl --user is-enabled --quiet imac-demo.service

echo
echo "Passed: $PASS"
echo "Failed: $FAIL"

[ "$FAIL" -eq 0 ]
