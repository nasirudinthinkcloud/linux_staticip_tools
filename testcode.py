#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TOOL_NAME = "Linux Static IP + DNS Configurator"

BANNER = r"""
░▒▓███████▓▒░ ░▒▓██████▓▒░ ░▒▓███████▓▒░▒▓█▓▒░░▒▓█▓▒░░▒▓██████▓▒░░▒▓█▓▒░░▒▓█▓▒░░▒▓██████▓▒░░▒▓█▓▒░░▒▓█▓▒░░▒▓██████▓▒░  
░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░      ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░ 
░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░      ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░ 
░▒▓█▓▒░░▒▓█▓▒░▒▓████████▓▒░░▒▓██████▓▒░ ░▒▓██████▓▒░░▒▓████████▓▒░▒▓████████▓▒░▒▓████████▓▒░░▒▓██████▓▒░░▒▓████████▓▒░ 
░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░      ░▒▓█▓▒░  ░▒▓█▓▒░   ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░  ░▒▓█▓▒░   ░▒▓█▓▒░░▒▓█▓▒░ 
░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░      ░▒▓█▓▒░  ░▒▓█▓▒░   ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░  ░▒▓█▓▒░   ░▒▓█▓▒░░▒▓█▓▒░ 
░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓███████▓▒░   ░▒▓█▓▒░   ░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░▒▓█▓▒░░▒▓█▓▒░  ░▒▓█▓▒░   ░▒▓█▓▒░░▒▓█▓▒░ 
                                                                                                                                                                                                                                            
"""

def run(cmd, check=True, capture=False):
    if capture:
        return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.run(cmd, check=check)

def which(cmd):
    return shutil.which(cmd) is not None

def require_root():
    if os.geteuid() != 0:
        print("ERROR: Run as root (sudo).", file=sys.stderr)
        sys.exit(1)

def ts():
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def backup_file(path: Path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + f".bak.{ts()}")
        shutil.copy2(path, bkp)
        return bkp
    return None

def get_default_iface():
    try:
        r = run(["ip", "route", "show", "default"], capture=True)
        for line in r.stdout.splitlines():
            m = re.search(r"\bdev\s+(\S+)", line)
            if m:
                return m.group(1)
    except Exception:
        pass

    try:
        r = run(["ip", "-o", "link", "show", "up"], capture=True)
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                iface = parts[1].strip()
                if iface != "lo":
                    return iface
    except Exception:
        pass

    return None

def detect_stack():
    if which("netplan") and Path("/etc/netplan").exists():
        ymls = list(Path("/etc/netplan").glob("*.yaml")) + list(Path("/etc/netplan").glob("*.yml"))
        if ymls:
            return "netplan"

    if which("nmcli"):
        try:
            r = run(["nmcli", "-t", "-f", "RUNNING", "general"], capture=True)
            if "running" in r.stdout.lower():
                return "nmcli"
        except Exception:
            return "nmcli"

    if Path("/run/systemd/system").exists() and which("networkctl"):
        return "networkd"

    return "iproute2"

def normalize_ip_prefix(ip: str, prefix: int) -> str:
    return f"{ip}/{prefix}"

def prompt(msg, default=None, required=False, validator=None):
    while True:
        if default is not None:
            s = input(f"{msg} [{default}]: ").strip()
            if not s:
                s = str(default)
        else:
            s = input(f"{msg}: ").strip()

        if required and not s:
            print("  - This field is required.")
            continue

        if validator:
            ok, err = validator(s)
            if not ok:
                print(f"  - Invalid value: {err}")
                continue

        return s

def v_ipv4(s):
    # basic ipv4 validation
    parts = s.split(".")
    if len(parts) != 4:
        return False, "Not an IPv4 address"
    for p in parts:
        if not p.isdigit():
            return False, "IPv4 octets must be numeric"
        n = int(p)
        if n < 0 or n > 255:
            return False, "IPv4 octet out of range (0-255)"
    return True, ""

def v_prefix(s):
    if not s.isdigit():
        return False, "Prefix must be numeric"
    n = int(s)
    if n < 1 or n > 32:
        return False, "Prefix must be between 1 and 32"
    return True, ""

def v_dns_list(s):
    items = [x.strip() for x in s.split(",") if x.strip()]
    if not items:
        return False, "Provide at least one DNS server"
    for ip in items:
        ok, err = v_ipv4(ip)
        if not ok:
            return False, f"DNS '{ip}' invalid: {err}"
    return True, ""

def apply_nmcli(iface, ip, prefix, gw, dns_list, search_domain=None):
    active = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"], capture=True).stdout.strip().splitlines()
    con_name = None
    for line in active:
        if not line:
            continue
        name, dev = (line.split(":", 1) + [""])[:2]
        if dev == iface:
            con_name = name
            break

    if not con_name:
        allc = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show"], capture=True).stdout.strip().splitlines()
        for line in allc:
            if not line:
                continue
            name, dev = (line.split(":", 1) + [""])[:2]
            if dev == iface:
                con_name = name
                break

    if not con_name:
        con_name = f"static-{iface}"
        run(["nmcli", "connection", "add", "type", "ethernet", "ifname", iface, "con-name", con_name])

    dns_csv = ",".join(dns_list)

    run(["nmcli", "connection", "modify", con_name, "ipv4.method", "manual"])
    run(["nmcli", "connection", "modify", con_name, "ipv4.addresses", normalize_ip_prefix(ip, prefix)])
    run(["nmcli", "connection", "modify", con_name, "ipv4.gateway", gw])
    run(["nmcli", "connection", "modify", con_name, "ipv4.dns", dns_csv])

    if search_domain:
        run(["nmcli", "connection", "modify", con_name, "ipv4.dns-search", search_domain])
    else:
        run(["nmcli", "connection", "modify", con_name, "ipv4.dns-search", ""])

    run(["nmcli", "connection", "modify", con_name, "connection.autoconnect", "yes"])

    run(["nmcli", "connection", "down", con_name], check=False)
    run(["nmcli", "connection", "up", con_name])

def apply_networkd(iface, ip, prefix, gw, dns_list, search_domain=None):
    netdir = Path("/etc/systemd/network")
    netdir.mkdir(parents=True, exist_ok=True)
    f = netdir / f"10-{iface}.network"
    backup_file(f)

    dns_line = " ".join(dns_list)
    content = [
        "[Match]",
        f"Name={iface}",
        "",
        "[Network]",
        f"Address={normalize_ip_prefix(ip, prefix)}",
        f"Gateway={gw}",
        f"DNS={dns_line}",
    ]
    if search_domain:
        content.append(f"Domains={search_domain}")

    f.write_text("\n".join(content) + "\n")

    run(["systemctl", "enable", "--now", "systemd-networkd"], check=False)
    run(["systemctl", "restart", "systemd-networkd"], check=False)

def apply_netplan(iface, ip, prefix, gw, dns_list, search_domain=None):
    netplan_dir = Path("/etc/netplan")
    ymls = sorted(list(netplan_dir.glob("*.yaml")) + list(netplan_dir.glob("*.yml")))
    target = ymls[0] if ymls else (netplan_dir / "99-static-ip.yaml")
    backup_file(target)

    dns_yaml = "\n".join([f"          - {d}" for d in dns_list])

    search_yaml = ""
    if search_domain:
        search_yaml = f"\n        search:\n          - {search_domain}"

    content = f"""network:
  version: 2
  ethernets:
    {iface}:
      dhcp4: no
      addresses:
        - {normalize_ip_prefix(ip, prefix)}
      routes:
        - to: default
          via: {gw}
      nameservers:
        addresses:
{dns_yaml}{search_yaml}
"""
    target.write_text(content)

    run(["netplan", "generate"])
    run(["netplan", "apply"])

def apply_iproute2_temp(iface, ip, prefix, gw, dns_list, search_domain=None):
    run(["ip", "addr", "flush", "dev", iface], check=False)
    run(["ip", "addr", "add", normalize_ip_prefix(ip, prefix), "dev", iface])
    run(["ip", "link", "set", iface, "up"])
    run(["ip", "route", "replace", "default", "via", gw, "dev", iface])

    resolv = Path("/etc/resolv.conf")
    if resolv.exists() and not resolv.is_symlink():
        backup_file(resolv)
        lines = []
        if search_domain:
            lines.append(f"search {search_domain}")
        for d in dns_list:
            lines.append(f"nameserver {d}")
        resolv.write_text("\n".join(lines) + "\n")

def main():
    require_root()

    print(BANNER.rstrip())
    print(f"{TOOL_NAME}\n")

    detected_iface = get_default_iface() or ""
    iface = prompt("Interface (Enter for auto-detect)", default=detected_iface if detected_iface else None, required=False)
    if not iface:
        iface = get_default_iface()

    if not iface:
        print("ERROR: Could not detect interface. Please enter interface name (e.g., eth0).", file=sys.stderr)
        sys.exit(2)

    ip = prompt("Static IP", required=True, validator=v_ipv4)
    prefix = int(prompt("CIDR Prefix", default="24", required=True, validator=v_prefix))
    gw = prompt("Gateway", required=True, validator=v_ipv4)
    dns_raw = prompt("DNS servers (comma-separated)", required=True, validator=v_dns_list)
    dns_list = [x.strip() for x in dns_raw.split(",") if x.strip()]
    search_domain = prompt("DNS search domain (optional)", default="", required=False).strip() or None

    backend = detect_stack()

    print("\n[SUMMARY]")
    print(f"  Interface : {iface}")
    print(f"  Address   : {ip}/{prefix}")
    print(f"  Gateway   : {gw}")
    print(f"  DNS       : {', '.join(dns_list)}")
    print(f"  Search    : {search_domain or '-'}")
    print(f"  Backend   : {backend}")

    try:
        if backend == "nmcli":
            apply_nmcli(iface, ip, prefix, gw, dns_list, search_domain)
        elif backend == "netplan":
            apply_netplan(iface, ip, prefix, gw, dns_list, search_domain)
        elif backend == "networkd":
            apply_networkd(iface, ip, prefix, gw, dns_list, search_domain)
        else:
            print("\n[WARN] No persistent network manager detected. Applying temporary config via iproute2.")
            apply_iproute2_temp(iface, ip, prefix, gw, dns_list, search_domain)

        print("\n[OK] Configuration applied.")
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Command failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
