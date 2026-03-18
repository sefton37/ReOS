"""Smoke tests for Plan A extended scoring matchers."""
import sys
sys.path.insert(0, "/home/kellogg/dev/ReOS")

from benchmarks.matching import (
    structural_match,
    sudo_normalized_match,
    command_equivalence_match,
    placeholder_normalized_match,
)

errors = []

def check(label, result, expected):
    if result != expected:
        errors.append(f"FAIL [{label}]: got {result!r}, want {expected!r}")
    else:
        print(f"  ok  {label}")

# ── structural_match ──────────────────────────────────────────────────────────
check("structural same base", structural_match("ls -la /tmp", "ls /home"), True)
check("structural strips sudo", structural_match("sudo ls /tmp", "ls /home"), True)
check("structural different base", structural_match("find /tmp -name foo", "ls"), False)
check("structural None actual", structural_match(None, "ls"), False)
check("structural None expected", structural_match("ls", None), False)
check("structural via alts", structural_match("grep -r foo", "ls", ["grep pattern"]), True)

# ── sudo_normalized_match ─────────────────────────────────────────────────────
check("sudo strip match", sudo_normalized_match("sudo apt-get update", "apt-get update"), True)
check("sudo strip reverse", sudo_normalized_match("apt-get update", "sudo apt-get update"), True)
check("exact no sudo", sudo_normalized_match("apt-get update", "apt-get update"), True)
check("sudo no match", sudo_normalized_match("apt-get install foo", "apt-get update"), False)
check("sudo both None", sudo_normalized_match(None, None), True)
check("sudo None actual", sudo_normalized_match(None, "ls"), False)

# ── command_equivalence_match ─────────────────────────────────────────────────
check("equiv netstat/ss", command_equivalence_match("ss -tlnp", "netstat -tlnp"), True)
check("equiv killall/pkill", command_equivalence_match("pkill nginx", "killall nginx"), True)
check("equiv ss/netstat reverse", command_equivalence_match("netstat -an", "ss -an"), True)
check("equiv no match", command_equivalence_match("ls", "find"), False)
check("equiv None actual", command_equivalence_match(None, "netstat"), False)
check("equiv None expected", command_equivalence_match("ss", None), False)
check("equiv via alts", command_equivalence_match("pkill foo", "ls", ["killall foo"]), True)

# ── placeholder_normalized_match ──────────────────────────────────────────────
# <username> -> PARAM, {username} -> PARAM — both reduce to the same form
check("placeholder angle bracket", placeholder_normalized_match("adduser <username>", "adduser {username}"), True)
# newuser and newadmin both map to USER
check("placeholder USER variants", placeholder_normalized_match("useradd newuser", "useradd newadmin"), True)
check("placeholder /path/to/", placeholder_normalized_match("cat /path/to/file.txt", "cat /path/to/notes.txt"), True)
check("placeholder file.ext", placeholder_normalized_match("rm file.txt", "rm file.log"), True)
check("placeholder no match", placeholder_normalized_match("ls /tmp", "ls /home"), False)
check("placeholder both None", placeholder_normalized_match(None, None), True)
check("placeholder None actual", placeholder_normalized_match(None, "ls"), False)
check("placeholder /dev/disk", placeholder_normalized_match("dd if=/dev/sda of=img", "dd if=/dev/sdb of=img"), True)
check("placeholder curly brace", placeholder_normalized_match("tar -xf {archive}", "tar -xf {tarball}"), True)

if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print(f"\nAll {len([None for _ in range(100) if False]) or 'smoke'} tests passed.")
