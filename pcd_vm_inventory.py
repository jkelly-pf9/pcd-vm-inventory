#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openstacksdk==4.21.0",
#     "keystoneauth1==5.18.0",
#     "osprofiler==4.4.0",
# ]
# ///
#
# Copyright 2026 Platform9 Systems, Inc.
"""
pcd_vm_inventory.py: export every VM in a Platform9 Private Cloud Director
(PCD) deployment to CSV, across all Regions and all tenants (projects).

The script is read-only. Apart from the Keystone login, it sends only GET
requests and makes no changes to the deployment.

Requirements
  - Python 3.11 or later (uv installs a suitable Python automatically).
  - Credentials with the admin role. Listing VMs across every project needs
    it; the script stops with an error if the role is missing.

Running
  uv run pcd_vm_inventory.py -o vms.csv              (recommended)
  pipx run pcd_vm_inventory.py -o vms.csv
  Or in a virtual environment:
    python3 -m venv .venv && . .venv/bin/activate
    pip install openstacksdk==4.21.0 keystoneauth1==5.18.0 osprofiler==4.4.0
    python pcd_vm_inventory.py -o vms.csv

Authentication
  Recommended: an application credential in clouds.yaml. It can be given an
  expiry date and revoked when the export is done, and no account password
  is stored on disk.
    1. Log in as an admin user and create the credential:
         openstack application credential create pcd-vm-inventory \\
             --role admin --expiration 2026-12-31T00:00:00
    2. Add it to ./clouds.yaml or ~/.config/openstack/clouds.yaml, and make
       the file readable only by you (chmod 600):
         clouds:
           pcd:
             auth_type: v3applicationcredential
             auth:
               auth_url: https://<pcd-fqdn>/keystone/v3
               application_credential_id: <id>
               application_credential_secret: <secret>
             identity_api_version: 3
             interface: public
    3. uv run pcd_vm_inventory.py --cloud pcd -o vms.csv
       Repeat --cloud to export several PCD deployments into one CSV.

  Alternative: the RC file downloaded from the PCD UI. Do not keep the
  password in the file; enter it when you run the script:
    source admin-openrc.sh
    read -rs OS_PASSWORD && export OS_PASSWORD
    uv run pcd_vm_inventory.py -o vms.csv

  Alternative: an existing Keystone token. Use OS_* variables, not
  clouds.yaml; OS_* variables are ignored when --cloud is given. Set
  OS_AUTH_TYPE to v3token (the RC file's "password" ignores the token) and
  give a project, or the token has no roles or catalog:
    export OS_AUTH_TYPE=v3token
    export OS_AUTH_URL=https://<pcd-fqdn>/keystone/v3
    export OS_PROJECT_NAME=service OS_PROJECT_DOMAIN_NAME=Default
    read -rs OS_TOKEN && export OS_TOKEN
    uv run pcd_vm_inventory.py -o vms.csv
  A token cannot be renewed. If it expires during the run, later Regions
  fail and the script exits with code 2. Use an application credential for
  long exports.

Private CA on the management plane
  Set OS_CACERT (or cacert: in clouds.yaml) to the CA bundle. Python uses
  certifi's bundle, not the system trust store, so update-ca-certificates
  alone is not enough. Do not disable certificate verification.

Windows
  Run from PowerShell; WSL is not needed. Every dependency has a prebuilt
  Windows wheel, so no compiler is required.
    1. Install uv:  winget install --id=astral-sh.uv -e
    2. Use clouds.yaml as above. On Windows it is read from the current
       directory, %LOCALAPPDATA%\\OpenStack\\openstack\\, or
       %USERPROFILE%\\.config\\openstack\\.
    3. uv run pcd_vm_inventory.py --cloud pcd -o vms.csv

  Without internet access (uv cannot download Python or packages), build
  the offline bundle on a Linux or macOS machine that has uv:
    ./build_windows_bundle.sh
  Copy dist/pcd-vm-inventory-windows-x64.zip to the Windows machine and
  unzip it. It holds Python, every dependency, and run.cmd, which takes the
  same options as the script:
    .\\pcd-vm-inventory\\run.cmd --cloud pcd -o vms.csv
  If the zip was downloaded in a browser, run Unblock-File on it before
  unzipping.

  The RC file is a bash script and cannot be sourced in PowerShell. To use
  a Keystone token instead, set the OS_* variables in PowerShell, enter the
  token at a prompt, and omit --cloud (see the token notes above):
    $env:OS_AUTH_TYPE = "v3token"
    $env:OS_AUTH_URL = "https://<pcd-fqdn>/keystone/v3"
    $env:OS_PROJECT_NAME = "service"
    $env:OS_PROJECT_DOMAIN_NAME = "Default"
    $env:OS_TOKEN = [Net.NetworkCredential]::new('',
        (Read-Host -AsSecureString 'Token')).Password
    uv run pcd_vm_inventory.py -o vms.csv

  Windows ignores Unix file modes, so chmod 600 has no effect and the CSV
  is not made owner-only: it takes the access rules of its folder. Keep
  clouds.yaml and the CSV in a folder under your user profile, not a
  shared one such as C:\\temp. For a private CA, set
  $env:OS_CACERT = "C:\\path\\to\\ca.pem"; adding the CA to the Windows
  certificate store is not enough.

Output
  - One row per VM. The CSV is UTF-8 with a byte-order mark so Excel shows
    non-ASCII names correctly, and is created readable only by its owner
    (Linux and macOS; see Windows above) because it contains user names,
    email addresses, and VM details.
  - Text that a spreadsheet would run as a formula (a leading =, +, -, @,
    tab, or carriage return) is prefixed with a single quote. VM names and
    other tenant-supplied text cannot run as formulas when the file is opened.
  - Columns that can be blank:
      instance_name, key_name, tags   Blank when data_source is "cqrs"; the
                                      CQRS service does not return them.
      image_name, image_id            Blank for VMs that boot from a volume.
      fixed_ips, floating_ips,        Blank when the VM has no addresses
      mac_addresses                   recorded in Nova.
      server_group                    Blank when the VM is in no server group.
      volume_total_gb                 Blank when no volume size is known.
  - VM metadata is left out by default because users can store arbitrary
    values, including secrets, there. Add --include-metadata to export it.
  - data_source records which API served the Region: "cqrs" or "native".

Exit codes
  0  all Regions exported
  1  fatal error (authentication failure, no Regions found)
  2  CSV written, but one or more Regions failed (partial inventory)

Distributed tracing (for Platform9 support)
  --os-profile <HMAC_KEY> enables osprofiler. Every API call in the run
  carries the same base trace ID, printed at the start and end of the run.
  The PCD default HMAC key is PF9_TRACE.

How data is read
  Inventory reads go to the PCD CQRS read service first (paths under /pf9/
  on each Region FQDN), which reduces load on the OpenStack APIs. The native
  OpenStack APIs are used where CQRS has no equivalent, or as a per-call
  fallback when a CQRS call fails.

  Data                 CQRS endpoint (primary)                     Native fallback
  -------------------  ------------------------------------------  ----------------------------
  VM list              /pf9/vmslist?all_tenants=true&domain_id=    nova /servers/detail
                       (one call set per Keystone domain, merged)
  VM count check       /pf9/vmslist?count_only=true&domain_id=     (none, check skipped)
  Flavors              /pf9/nova/{tenant_id}/flavors/detail        nova /flavors/detail
  Images               /pf9/glance/v2/images                       glance /images
  Volumes              /pf9/cinder/{tenant_id}/volumes             cinder /volumes/detail
  Server groups        /pf9/nova/{tenant_id}/os-server-groups      nova /os-server-groups
  Host names           /pf9/resmgr/v2/hosts                        (none, column left blank)
  Floating IPs         (none: CQRS ports requires network_id)      neutron /floatingips + /ports
  Domains/projects/    (none: Keystone is not in CQRS)             keystone, once per run
  users

  vmslist embeds flavor, image name, volume size, and host name in each VM
  record (native Nova 2.47 embeds flavor only). The Flavors, Images, Volumes,
  and Host names calls are made only when some VM in the Region lacks the
  embedded value.

  {tenant_id} is the project the admin token is scoped to; all_tenants=true
  widens the read to every project. vmslist rejects requests without
  domain_id (HTTP 400 "missing domain_id").

  A /pf9/ path with no ingress route falls through to the PCD web UI and
  returns HTML with HTTP 200. That is reported as "non-JSON ... likely not
  routed" and handled like any other CQRS failure.

Examples
  uv run pcd_vm_inventory.py --cloud pcd -o vms.csv
  uv run pcd_vm_inventory.py --regions region1,region2 -o vms.csv
  uv run pcd_vm_inventory.py --no-fallback -o vms.csv
  uv run pcd_vm_inventory.py --os-profile PF9_TRACE -o vms.csv
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import openstack
    from keystoneauth1 import exceptions as ks_exc
except ImportError:
    sys.exit(
        f"openstacksdk is not importable from {sys.executable}.\n"
        "Run the script with its declared dependencies:\n"
        "  uv run pcd_vm_inventory.py ...   (or: pipx run pcd_vm_inventory.py ...)\n"
        "or install into a virtual environment:\n"
        "  python3 -m venv .venv && . .venv/bin/activate\n"
        "  pip install openstacksdk==4.21.0 keystoneauth1==5.18.0 osprofiler==4.4.0"
    )

__version__ = "0.1.0"

LOG = logging.getLogger("pcd_vm_inventory")

# Nova OS-EXT-STS:power_state integer codes.
POWER_STATES = {
    0: "NOSTATE",
    1: "RUNNING",
    3: "PAUSED",
    4: "SHUTDOWN",
    6: "CRASHED",
    7: "SUSPENDED",
}

# Nova 2.47+ embeds flavor details (vcpus, ram, disk) in each server record.
NOVA_MICROVERSION = "2.47"

# Neutron port IDs per filtered GET; keeps the query string a safe length.
PORT_LOOKUP_BATCH = 50

SOURCE_CQRS = "cqrs"
SOURCE_NATIVE = "native"

# Role required to list VMs in every project.
REQUIRED_ROLE = "admin"

COLUMNS = [
    "pcd_endpoint",
    "region",
    "domain_name",
    "project_name",
    "project_id",
    "vm_name",
    "vm_id",
    "status",
    "power_state",
    "vm_state",
    "task_state",
    "availability_zone",
    "compute_host",
    "host_name",
    "hypervisor_hostname",
    "instance_name",
    "server_group",
    "flavor_name",
    "vcpus",
    "ram_mb",
    "root_disk_gb",
    "ephemeral_gb",
    "boot_source",
    "image_name",
    "image_id",
    "volume_count",
    "volume_total_gb",
    "volume_ids",
    "networks",
    "fixed_ips",
    "floating_ips",
    "mac_addresses",
    "key_name",
    "user_name",
    "user_id",
    "created_at",
    "launched_at",
    "updated_at",
    "locked",
    "tags",
    "metadata",
    "data_source",
    "exported_at",
]

LIST_SEP = "; "

# Leading characters that make Excel, LibreOffice, and Google Sheets treat a
# cell as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

EPILOG = """exit codes:
  0  all Regions exported
  1  fatal error (authentication failure, no Regions found)
  2  CSV written, but one or more Regions failed (partial inventory)

instance_name, key_name, and tags are blank for Regions read from the CQRS
service. Authentication setup, output details, and the full list of blank
columns are documented at the top of this script.
"""


class CqrsUnavailable(Exception):
    """A CQRS call failed and native fallback is disabled."""


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------

def pick(d, *keys, default=None):
    """Return the first present, non-None value among keys in dict d."""
    for key in keys:
        value = d.get(key)
        if value is not None:
            return value
    return default


def open_private(path, encoding):
    """Open path for writing, readable and writable by the owner only."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if hasattr(os, "fchmod"):
        os.fchmod(fd, 0o600)  # an existing file keeps its old mode otherwise
    return os.fdopen(fd, "w", newline="", encoding=encoding)


def describe_error(exc):
    """Return a plain-language message for common connection and login failures.

    keystoneauth wraps TLS and connection errors during login in a
    DiscoveryFailure, so the exception chain is searched for the cause.
    """
    cause = exc
    while cause is not None:
        if isinstance(cause, ks_exc.Unauthorized):
            return ("login failed (HTTP 401). Check the user name, password, project, "
                    "and domain, or the application credential ID and secret.")
        if isinstance(cause, ks_exc.SSLError):
            return ("TLS certificate verification failed. If the PCD management plane "
                    "uses a private CA, set OS_CACERT (or cacert: in clouds.yaml) to "
                    f"its CA bundle. Detail: {cause}")
        if isinstance(cause, ks_exc.ConnectionError):
            return (f"could not connect. Check the URL, DNS, and any proxy or "
                    f"firewall between this machine and PCD. Detail: {cause}")
        if isinstance(cause, (openstack.exceptions.ConfigException,
                              ks_exc.MissingRequiredOptions)):
            return f"incomplete configuration: {cause}"
        cause = cause.__cause__ or cause.__context__
    return str(exc)


def response_json(resp, what):
    """Return parsed JSON from a requests-style response.

    Raises on HTTP errors, and on a 2xx body that is not JSON. The second case
    is what an unrouted /pf9/ path looks like: the request falls through to
    the PCD web UI, which answers 200 with HTML.
    """
    if resp.status_code >= 400:
        raise RuntimeError(f"{what}: HTTP {resp.status_code} {resp.text[:200].strip()}")
    try:
        return resp.json()
    except ValueError:
        ctype = resp.headers.get("Content-Type", "unknown") if resp.headers else "unknown"
        raise RuntimeError(
            f"{what}: HTTP {resp.status_code} returned non-JSON ({ctype}); "
            "the endpoint is likely not routed on this Region"
        ) from None


def extract_list(body, list_key):
    """Return the item list from a bare list or {list_key: [...]}.

    An empty object counts as an empty list: vmslist answers {} for a Region
    with no VMs. Any other shape raises, so an unexpected CQRS response falls
    back to the native API instead of exporting an empty list.
    """
    if isinstance(body, list):
        return body
    if body == {}:
        return []
    if isinstance(body, dict) and isinstance(body.get(list_key), list):
        return body[list_key]
    found = f"keys {sorted(body)}" if isinstance(body, dict) else type(body).__name__
    raise RuntimeError(f"response has no '{list_key}' list (got {found})")


# vmslist reports status as the lowercase Nova vm_state ("stopped"), where
# Nova's API reports its own status vocabulary ("SHUTOFF"). Mapped so the
# status column is the same whichever path served the Region. Values not
# listed are uppercased.
CQRS_STATUS_MAP = {
    "active": "ACTIVE",
    "building": "BUILD",
    "stopped": "SHUTOFF",
    "resized": "VERIFY_RESIZE",
    "paused": "PAUSED",
    "suspended": "SUSPENDED",
    "rescued": "RESCUE",
    "error": "ERROR",
    "deleted": "DELETED",
    "soft-delete": "SOFT_DELETED",
    "shelved": "SHELVED",
    "shelved_offloaded": "SHELVED_OFFLOADED",
}


def normalize_vm(vm):
    """Return a vmslist record with status in Nova's vocabulary."""
    out = dict(vm)
    status = out.get("status")
    if isinstance(status, str) and status.islower():
        out["status"] = CQRS_STATUS_MAP.get(status, status.upper())
    return out


def paginate(get_page, list_key, page_size):
    """Yield every item from a limit/marker paginated list API.

    get_page(params) returns the parsed response body. The marker is the ID of
    the last item on the previous page. Stops on a short page, an empty page,
    or a page with no new IDs (guards against a server that ignores marker).
    """
    seen = set()
    marker = None
    while True:
        params = {"limit": page_size}
        if marker:
            params["marker"] = marker
        items = extract_list(get_page(params), list_key)
        new_items = [i for i in items if i.get("id") not in seen]
        for item in new_items:
            seen.add(item.get("id"))
            yield item
        if len(items) < page_size or not new_items:
            return
        marker = items[-1].get("id")


# --------------------------------------------------------------------------
# Connection and discovery
# --------------------------------------------------------------------------

def connect(cloud):
    """Open the authenticating connection from clouds.yaml or OS_* env vars."""
    return openstack.connect(cloud=cloud) if cloud else openstack.connect()


def region_connection(base, region):
    """Return a connection to one Region that reuses base's authenticated session.

    openstack.connect(region_name=...) validates the Region against the
    configured list, which for an RC file is only OS_REGION_NAME. Building
    from the session skips that check, routes by the Keystone catalog, and
    reuses the existing token instead of re-authenticating per Region.
    """
    return openstack.connection.Connection(
        session=base.session,
        region_name=region,
        interface=base.config.get_interface() or "public",
    )


def endpoint_label(conn, cloud):
    """Human-readable identifier for the PCD deployment: the auth URL host."""
    auth_url = (conn.config.config.get("auth") or {}).get("auth_url", "")
    return urlparse(auth_url).hostname or cloud or "env"


def check_access(conn, pcd_endpoint):
    """Log in, and stop early if the credentials cannot see every project."""
    access = conn.session.auth.get_access(conn.session)
    roles = sorted(access.role_names or [])
    if REQUIRED_ROLE not in roles:
        raise RuntimeError(
            f"[{pcd_endpoint}] the credentials have roles {', '.join(roles) or '(none)'} "
            f"on project {access.project_name}. The {REQUIRED_ROLE} role is required "
            "to list VMs in every project; without it the inventory would be incomplete."
        )
    if conn.session.verify is False:
        LOG.warning("[%s] TLS certificate verification is disabled. Set OS_CACERT "
                    "to the management plane's CA bundle instead.", pcd_endpoint)


def discover_regions(conn):
    """Return {region_name: base_url} for every Region with a compute endpoint.

    base_url is scheme://host of the Region's compute endpoint. CQRS paths
    (/pf9/...) hang off that root.
    """
    access = conn.session.auth.get_access(conn.session)
    interface = conn.config.get_interface() or "public"
    endpoints = access.service_catalog.get_endpoints(
        service_type="compute", interface=interface
    )
    regions = {}
    for ep in endpoints.get("compute", []):
        if not ep:
            continue
        name = ep.get("region_name") or ep.get("region_id") or ep.get("region")
        url = urlparse(ep.get("url", ""))
        if name and url.scheme and url.netloc:
            regions[name] = f"{url.scheme}://{url.netloc}"
    return dict(sorted(regions.items()))


def safe_list(description, fn):
    """Run a list call; on failure log a warning and return an empty list."""
    try:
        return list(fn())
    except Exception as exc:  # noqa: BLE001 - degrade, do not abort the export
        LOG.warning("Could not list %s: %s", description, describe_error(exc))
        return []


def load_identity(conn):
    """Return (projects, users, domain_ids) from Keystone (native, once per run).

    projects:   project_id -> (project_name, domain_name)
    users:      user_id -> user_name
    domain_ids: every domain ID, used to scope vmslist calls
    """
    domains = {d.id: d.name for d in safe_list("domains", conn.identity.domains)}
    projects = {
        p.id: (p.name, domains.get(p.domain_id, p.domain_id or ""))
        for p in safe_list("projects", conn.identity.projects)
    }
    users = {u.id: u.name for u in safe_list("users", conn.identity.users)}
    LOG.info("Keystone: %d domains, %d projects, %d users",
             len(domains), len(projects), len(users))
    return projects, users, list(domains)


# --------------------------------------------------------------------------
# Per-Region reader: CQRS first, native fallback
# --------------------------------------------------------------------------

class RegionReader:
    """All inventory reads for one Region.

    CQRS calls go through the shared keystoneauth session, which supplies the
    token, TLS settings, and (when enabled) osprofiler trace headers. Native
    calls use a per-Region openstacksdk connection created on first use.
    """

    def __init__(self, base_conn, region, base_url, tenant_id, domain_ids,
                 page_size, allow_fallback, dump_dir=None):
        self.dump_dir = dump_dir
        self._dumped = set()
        self.base_conn = base_conn
        self.session = base_conn.session
        self.region = region
        self.base_url = base_url
        self.tenant_id = tenant_id
        # The token's own project domain first; it must succeed for CQRS to be used.
        self.domain_ids = domain_ids
        self.page_size = page_size
        self.allow_fallback = allow_fallback
        self._native = None
        # domain_id -> VM count reported by vmslist count_only.
        self.reported_counts = {}

    # -- transport ---------------------------------------------------------

    @property
    def native(self):
        if self._native is None:
            self._native = region_connection(self.base_conn, self.region)
        return self._native

    def cqrs_get(self, path, params):
        url = f"{self.base_url}/pf9/{path.lstrip('/')}"
        resp = self.session.get(url, params=params, raise_exc=False)
        self.dump(path, params, resp)
        return response_json(resp, f"GET {url}")

    def dump(self, path, params, resp):
        """With --dump-cqrs, save the first raw response per Region and endpoint.

        Only the first page of a paginated endpoint is saved.
        """
        if not self.dump_dir:
            return
        variant = "count" if params.get("count_only") else "list"
        name = f"{self.region}-{path.strip('/').replace('/', '_')}-{variant}"
        if name in self._dumped:
            return
        self._dumped.add(name)
        os.makedirs(self.dump_dir, mode=0o700, exist_ok=True)
        target = os.path.join(self.dump_dir, f"{name}.txt")
        with open_private(target, "utf-8") as fh:
            fh.write(f"GET {path}\nparams: {json.dumps(params, sort_keys=True)}\n")
            fh.write(f"status: {resp.status_code}\n")
            fh.write(f"content-type: {resp.headers.get('Content-Type', '') if resp.headers else ''}\n\n")
            fh.write(resp.text)
        LOG.info("[%s] dumped %s", self.region, target)

    @staticmethod
    def native_get(proxy, path, params, microversion=None):
        kwargs = {"params": params, "raise_exc": False}
        if microversion:
            kwargs["microversion"] = microversion
        resp = proxy.get(path, **kwargs)
        return response_json(resp, f"GET {path}")

    def with_fallback(self, what, cqrs_fn, native_fn, critical=False):
        """Run cqrs_fn; on failure log and run native_fn (if allowed).

        Returns (result, source). native_fn of None means no native
        equivalent exists; the caller receives (None, None).

        critical=True (the VM list) lets a native failure fail the Region.
        critical=False (enrichment lookups) logs a native failure and returns
        (None, None), so the affected column is blank and the Region survives.
        """
        try:
            return cqrs_fn(), SOURCE_CQRS
        except Exception as exc:  # noqa: BLE001
            if not self.allow_fallback:
                raise CqrsUnavailable(f"{what}: {exc}") from exc
            if native_fn is None:
                LOG.warning("[%s] CQRS %s failed, no native equivalent: %s",
                            self.region, what, describe_error(exc))
                return None, None
            LOG.warning("[%s] CQRS %s failed, falling back to native API: %s",
                        self.region, what, describe_error(exc))
        try:
            return native_fn(), SOURCE_NATIVE
        except Exception as exc:  # noqa: BLE001
            if critical:
                raise
            LOG.warning("[%s] native %s also failed, column left blank: %s",
                        self.region, what, describe_error(exc))
            return None, None

    # -- VMs ---------------------------------------------------------------

    def servers(self):
        """Return (servers, source). Each server is a Nova-shaped dict.

        vmslist requires domain_id. It is queried once per Keystone domain and
        merged by VM ID, so the result is complete whether domain_id filters
        results or only sets authorization context. The token's own domain is
        queried first; if it fails, the whole VM list falls back. A failure in
        any other domain is logged and that domain is skipped.
        """
        def cqrs():
            merged = {}
            for index, domain_id in enumerate(self.domain_ids):
                try:
                    listed = self.cqrs_domain_servers(domain_id)
                except Exception as exc:  # noqa: BLE001
                    if index == 0:
                        raise
                    LOG.warning("[%s] vmslist for domain %s failed, VMs in that "
                                "domain may be missing: %s",
                                self.region, domain_id, describe_error(exc))
                    continue
                for server in listed:
                    merged.setdefault(server.get("id"), server)
            return list(merged.values())

        def native():
            return list(paginate(
                lambda p: self.native_get(
                    self.native.compute, "/servers/detail",
                    {"all_tenants": "True", **p}, NOVA_MICROVERSION,
                ),
                "servers", self.page_size,
            ))

        return self.with_fallback("VM list", cqrs, native, critical=True)

    def cqrs_domain_servers(self, domain_id):
        """Page vmslist for one domain and check the result against count_only."""
        base = {"tenant_id": self.tenant_id, "domain_id": domain_id,
                "all_tenants": "true"}
        listed = [normalize_vm(vm) for vm in paginate(
            lambda p: self.cqrs_get("vmslist", {**base, **p}), "vms", self.page_size)]
        expected = self.cqrs_vm_count(base)
        if expected is None:
            return listed
        self.reported_counts[domain_id] = expected
        if expected and not listed:
            # Fail so the Region falls back instead of exporting zero VMs.
            raise RuntimeError(f"vmslist returned 0 VMs but its count reports {expected}")
        if len(listed) != expected:
            LOG.warning("[%s] vmslist domain %s returned %d VMs but its count "
                        "reports %d; VMs may have been created or deleted during "
                        "the export", self.region, domain_id, len(listed), expected)
        return listed

    def cqrs_vm_count(self, base_params):
        """Return TOTAL_COUNT from vmslist count_only, or None if unavailable."""
        try:
            body = self.cqrs_get("vmslist", {**base_params, "count_only": "true"})
            return (body.get("server_counts") or {}).get("TOTAL_COUNT")
        except Exception as exc:  # noqa: BLE001 - the check is advisory
            LOG.warning("[%s] VM count check unavailable: %s",
                        self.region, describe_error(exc))
            return None

    # -- lookups -----------------------------------------------------------

    def flavors(self):
        """Return flavor_id -> flavor dict."""
        def cqrs():
            body = self.cqrs_get(f"nova/{self.tenant_id}/flavors/detail",
                                 {"is_public": "None"})
            return extract_list(body, "flavors")

        def native():
            body = self.native_get(self.native.compute, "/flavors/detail",
                                   {"is_public": "None"})
            return extract_list(body, "flavors")

        items, _ = self.with_fallback("flavors", cqrs, native)
        return {f["id"]: f for f in items or [] if f.get("id")}

    def images(self):
        """Return image_id -> image name."""
        def cqrs():
            return list(paginate(
                lambda p: self.cqrs_get("glance/v2/images", p),
                "images", self.page_size,
            ))

        def native():
            return list(paginate(
                lambda p: self.native_get(self.native.image, "/images", p),
                "images", self.page_size,
            ))

        items, _ = self.with_fallback("images", cqrs, native)
        return {i["id"]: i.get("name") or "" for i in items or [] if i.get("id")}

    def volume_sizes(self):
        """Return volume_id -> size_gb (None when the API omits size)."""
        def cqrs():
            base = {"all_tenants": "true"}
            return list(paginate(
                lambda p: self.cqrs_get(f"cinder/{self.tenant_id}/volumes",
                                        {**base, **p}),
                "volumes", self.page_size,
            ))

        def native():
            return list(paginate(
                lambda p: self.native_get(self.native.block_storage,
                                          "/volumes/detail",
                                          {"all_tenants": "True", **p}),
                "volumes", self.page_size,
            ))

        items, source = self.with_fallback("volumes", cqrs, native)
        sizes = {v["id"]: v.get("size") for v in items or [] if v.get("id")}
        if sizes and all(s is None for s in sizes.values()):
            LOG.warning("[%s] %s volume list carries no size field; "
                        "volume_total_gb will be blank", self.region, source)
        return sizes

    def server_groups(self):
        """Return vm_id -> server group name."""
        def cqrs():
            body = self.cqrs_get(f"nova/{self.tenant_id}/os-server-groups",
                                 {"all_projects": "true"})
            return extract_list(body, "server_groups")

        def native():
            body = self.native_get(self.native.compute, "/os-server-groups",
                                   {"all_projects": "True"})
            return extract_list(body, "server_groups")

        groups, _ = self.with_fallback("server groups", cqrs, native)
        membership = {}
        for group in groups or []:
            for member in group.get("members") or []:
                membership[member] = group.get("name") or group.get("id", "")
        return membership

    def host_names(self):
        """Return resmgr host_id -> hostname. No native equivalent."""
        def cqrs():
            body = self.cqrs_get("resmgr/v2/hosts", {})
            return extract_list(body, "hosts")

        hosts, _ = self.with_fallback("hosts", cqrs, None)
        names = {}
        for h in hosts or []:
            info = h.get("info") or {}
            name = info.get("hostname") or h.get("hostname") or h.get("name")
            if h.get("id") and name:
                names[h["id"]] = name
        return names

    def floating_ips(self):
        """Return vm_id -> [floating IPs] from native Neutron.

        CQRS /pf9/neutron/v2.0/ports requires network_id, so it cannot do a
        cross-tenant sweep. This reads the floating IP list once, then only the
        ports those floating IPs are bound to.
        """
        net = self.native.network
        fips = list(paginate(
            lambda p: self.native_get(net, "/floatingips", p),
            "floatingips", self.page_size,
        ))
        by_port = {}
        for fip in fips:
            if fip.get("port_id") and fip.get("floating_ip_address"):
                by_port.setdefault(fip["port_id"], []).append(fip["floating_ip_address"])

        by_vm = {}
        port_ids = sorted(by_port)
        for start in range(0, len(port_ids), PORT_LOOKUP_BATCH):
            batch = port_ids[start:start + PORT_LOOKUP_BATCH]
            body = self.native_get(net, "/ports", {
                "id": batch, "fields": ["id", "device_id"],
            })
            for port in extract_list(body, "ports"):
                device = port.get("device_id")
                if device:
                    by_vm.setdefault(device, []).extend(by_port.get(port.get("id"), []))
        return by_vm


# --------------------------------------------------------------------------
# Row construction (works on Nova-shaped dicts from CQRS or native)
# --------------------------------------------------------------------------

def flavor_fields(server, flavors):
    """Return (name, vcpus, ram_mb, disk_gb, ephemeral_gb)."""
    f = server.get("flavor") or {}
    if f.get("vcpus") is not None:
        return (pick(f, "original_name", "name", default=""),
                f.get("vcpus"), f.get("ram"), f.get("disk"), f.get("ephemeral"))
    flavor_id = pick(f, "id", default=None) or server.get("instance_type_id")
    looked_up = flavors.get(flavor_id)
    if looked_up is None:
        return flavor_id or "", "", "", "", ""
    return (looked_up.get("name", ""), looked_up.get("vcpus"), looked_up.get("ram"),
            looked_up.get("disk"), pick(looked_up, "OS-FLV-EXT-DATA:ephemeral",
                                        "ephemeral", default=""))


def image_id_of(server):
    image = server.get("image")
    if isinstance(image, dict):
        return image.get("id")
    return image or None


# vmslist embeds image, volume, and host details in each VM record. Native
# Nova does not. The embedded values are used first; the matching lookup call
# is made only when some VM lacks them (see lookups_needed).

def embedded_image_name(server):
    return server.get("imageName") or (server.get("imageDetails") or {}).get("name")


def attached_volume_ids(server):
    return [v.get("id") for v in
            (server.get("os-extended-volumes:volumes_attached") or [])
            if v.get("id")]


def embedded_volume_sizes(server):
    """Return volume_id -> size_gb from vmslist volumeDetails."""
    return {vid: d.get("volume_size")
            for vid, d in (server.get("volumeDetails") or {}).items()
            if isinstance(d, dict)}


def embedded_host_name(server):
    return ((server.get("hostDetails") or {}).get("info") or {}).get("hostname")


def lookups_needed(servers):
    """Return the lookup names that some server cannot fill from its own record."""
    needed = set()
    for s in servers:
        if (s.get("flavor") or {}).get("vcpus") is None:
            needed.add("flavors")
        if image_id_of(s) and not embedded_image_name(s):
            needed.add("images")
        sizes = embedded_volume_sizes(s)
        if any(sizes.get(v) is None for v in attached_volume_ids(s)):
            needed.add("volumes")
        if s.get("OS-EXT-SRV-ATTR:host") and not embedded_host_name(s):
            needed.add("hosts")
    return needed


def address_fields(addresses, extra_floating):
    """Return (networks, fixed_ips, floating_ips, macs) as joined strings."""
    networks, fixed, floating, macs = [], [], [], []
    for net_name, entries in sorted((addresses or {}).items()):
        networks.append(net_name)
        for entry in entries or []:
            ip = entry.get("addr", "")
            if entry.get("OS-EXT-IPS:type") == "floating":
                floating.append(ip)
            elif ip:
                fixed.append(ip)
            mac = entry.get("OS-EXT-IPS-MAC:mac_addr")
            if mac and mac not in macs:
                macs.append(mac)
    for ip in extra_floating or []:
        if ip not in floating:
            floating.append(ip)
    return (LIST_SEP.join(networks), LIST_SEP.join(fixed),
            LIST_SEP.join(floating), LIST_SEP.join(macs))


def build_row(server, *, ctx, lookups, source):
    vm_id = server.get("id", "")
    project_id = server.get("tenant_id", "")
    project_name, domain_name = ctx["projects"].get(project_id, ("", ""))

    flavor_name, vcpus, ram_mb, disk_gb, ephemeral_gb = flavor_fields(
        server, lookups["flavors"])

    image_id = image_id_of(server)

    volume_ids = attached_volume_ids(server)
    embedded_sizes = embedded_volume_sizes(server)
    sizes = [pick(embedded_sizes, v, default=lookups["volumes"].get(v))
             for v in volume_ids]
    known = [s for s in sizes if s is not None]
    volume_total = sum(known) if known else ""

    networks, fixed_ips, floating_ips, macs = address_fields(
        server.get("addresses"), lookups["floating"].get(vm_id))

    power = server.get("OS-EXT-STS:power_state")
    power_label = POWER_STATES.get(power, "" if power is None else str(power))

    compute_host = server.get("OS-EXT-SRV-ATTR:host") or ""
    locked = server.get("locked")
    metadata = server.get("metadata")
    user_id = server.get("user_id", "")

    return {
        "pcd_endpoint": ctx["pcd_endpoint"],
        "region": ctx["region"],
        "domain_name": domain_name,
        "project_name": project_name,
        "project_id": project_id,
        "vm_name": server.get("name", ""),
        "vm_id": vm_id,
        "status": server.get("status", ""),
        "power_state": power_label,
        "vm_state": server.get("OS-EXT-STS:vm_state") or "",
        "task_state": server.get("OS-EXT-STS:task_state") or "",
        "availability_zone": server.get("OS-EXT-AZ:availability_zone") or "",
        "compute_host": compute_host,
        "host_name": embedded_host_name(server) or lookups["hosts"].get(compute_host, ""),
        "hypervisor_hostname": server.get("OS-EXT-SRV-ATTR:hypervisor_hostname") or "",
        "instance_name": server.get("OS-EXT-SRV-ATTR:instance_name") or "",
        "server_group": lookups["server_groups"].get(vm_id, ""),
        "flavor_name": flavor_name,
        "vcpus": vcpus,
        "ram_mb": ram_mb,
        "root_disk_gb": disk_gb,
        "ephemeral_gb": ephemeral_gb,
        "boot_source": "image" if image_id else "volume",
        "image_name": (embedded_image_name(server) or lookups["images"].get(image_id) or "")
                      if image_id else "",
        "image_id": image_id or "",
        "volume_count": len(volume_ids),
        "volume_total_gb": volume_total,
        "volume_ids": LIST_SEP.join(volume_ids),
        "networks": networks,
        "fixed_ips": fixed_ips,
        "floating_ips": floating_ips,
        "mac_addresses": macs,
        "key_name": server.get("key_name") or "",
        "user_name": ctx["users"].get(user_id, ""),
        "user_id": user_id,
        "created_at": server.get("created") or "",
        "launched_at": server.get("OS-SRV-USG:launched_at") or "",
        "updated_at": server.get("updated") or "",
        "locked": "" if locked is None else str(bool(locked)).lower(),
        "tags": LIST_SEP.join(server.get("tags") or []),
        "metadata": json.dumps(metadata, sort_keys=True) if metadata else "",
        "data_source": source,
        "exported_at": ctx["exported_at"],
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def export_region(reader, ctx, opts):
    """Return the CSV rows for one Region."""
    servers, source = reader.servers()
    LOG.info("[%s] %d VMs via %s", reader.region, len(servers), source)

    needed = lookups_needed(servers)
    if opts.skip_volumes:
        needed.discard("volumes")
    skipped = sorted({"flavors", "images", "volumes", "hosts"} - needed)
    if skipped:
        LOG.info("[%s] Lookups not needed (details embedded in VM records): %s",
                 reader.region, ", ".join(skipped))
    lookups = {
        "flavors": reader.flavors() if "flavors" in needed else {},
        "images": reader.images() if "images" in needed else {},
        "volumes": reader.volume_sizes() if "volumes" in needed else {},
        "server_groups": reader.server_groups(),
        "hosts": reader.host_names() if "hosts" in needed else {},
        "floating": {},
    }
    # Native Nova lists floating IPs in addresses. Whether vmslist does is not
    # yet confirmed, so CQRS-served Regions are enriched from Neutron.
    if source == SOURCE_CQRS and not opts.skip_floating_ips:
        try:
            lookups["floating"] = reader.floating_ips()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("[%s] floating IP lookup failed: %s",
                        reader.region, describe_error(exc))

    region_ctx = {**ctx, "region": reader.region}
    return [build_row(s, ctx=region_ctx, lookups=lookups, source=source)
            for s in servers]


def export_cloud(cloud, opts, exported_at):
    """Export all VMs for one PCD deployment.

    Returns (rows, failed_regions, region_counts). region_counts maps
    (endpoint, region) to (exported VM count, {domain_id: vmslist count}).
    """
    base = connect(cloud)
    pcd_endpoint = endpoint_label(base, cloud)
    check_access(base, pcd_endpoint)
    tenant_id = base.current_project_id

    regions = discover_regions(base)
    LOG.info("[%s] Regions with compute endpoints: %s",
             pcd_endpoint, ", ".join(regions) or "(none)")
    for region, base_url in regions.items():
        LOG.info("[%s]   %s -> %s", pcd_endpoint, region, base_url)
    if opts.region_filter:
        missing = sorted(opts.region_filter - set(regions))
        if missing:
            LOG.warning("[%s] Requested Regions not in catalog: %s",
                        pcd_endpoint, ", ".join(missing))
        regions = {r: u for r, u in regions.items() if r in opts.region_filter}
    if not regions:
        raise RuntimeError(f"[{pcd_endpoint}] no Regions to export")

    projects, users, domain_ids = load_identity(base)
    home_domain = base.session.auth.get_access(base.session).project_domain_id or "default"
    domain_ids = [home_domain] + sorted(d for d in domain_ids if d != home_domain)
    LOG.info("[%s] vmslist domains (token domain first): %s",
             pcd_endpoint, ", ".join(domain_ids))
    ctx = {
        "pcd_endpoint": pcd_endpoint,
        "projects": projects,
        "users": users,
        "exported_at": exported_at,
    }

    rows, failed, counts = [], [], {}
    for region, base_url in regions.items():
        reader = RegionReader(
            base_conn=base, region=region, base_url=base_url,
            tenant_id=tenant_id, domain_ids=domain_ids, page_size=opts.page_size,
            dump_dir=opts.dump_cqrs,
            allow_fallback=not opts.no_fallback,
        )
        try:
            region_rows = export_region(reader, ctx, opts)
            rows.extend(region_rows)
            counts[(pcd_endpoint, region)] = (len(region_rows), reader.reported_counts)
        except Exception as exc:  # noqa: BLE001 - one bad Region must not stop the rest
            LOG.error("[%s] Region %s failed: %s", pcd_endpoint, region, describe_error(exc))
            failed.append((pcd_endpoint, region))
    return rows, failed, counts


def csv_safe(value):
    """Prefix text a spreadsheet would run as a formula (CSV injection)."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def write_csv(rows, path, columns):
    rows.sort(key=lambda r: (
        r["pcd_endpoint"], r["region"], r["domain_name"],
        r["project_name"], r["vm_name"], r["vm_id"],
    ))
    # utf-8-sig adds a byte-order mark so Excel detects UTF-8.
    handle = sys.stdout if path == "-" else open_private(path, "utf-8-sig")
    try:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_safe(v) for k, v in row.items()})
    finally:
        if handle is not sys.stdout:
            handle.close()


def count_note(reported):
    """Return the vmslist count text for the summary, e.g. ' (vmslist reports 152)'."""
    if not reported:
        return ""
    if len(reported) == 1:
        return f" (vmslist reports {next(iter(reported.values()))})"
    return " (vmslist reports " + ", ".join(
        f"domain {d}: {n}" for d, n in reported.items()) + ")"


def enable_profiler(hmac_key):
    """Initialise osprofiler; keystoneauth then adds trace headers to every call."""
    try:
        from osprofiler import profiler
    except ImportError:
        sys.exit("--os-profile requires osprofiler: pip install osprofiler==4.4.0")
    profiler.init(hmac_key)
    return profiler.get().get_base_id()


def log_trace_id(trace_id):
    LOG.info("Trace ID: %s", trace_id)
    LOG.info("Short trace ID for OpenTracing-based drivers: %s",
             trace_id.replace("-", "")[-16:])
    LOG.info("Display trace data with: osprofiler trace show --html %s", trace_id)


def parse_args(argv):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = argparse.ArgumentParser(
        prog="pcd_vm_inventory.py",
        description="Export every VM in a Platform9 Private Cloud Director "
                    "deployment, across all Regions and projects, to CSV. "
                    "Read-only: makes no changes to the deployment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--cloud", action="append", default=[],
        help="clouds.yaml entry name. Repeat for multiple PCD deployments. "
             "Omit to use OS_* environment variables (RC file).",
    )
    p.add_argument(
        "--regions", default="",
        help="Comma-separated Region names to include. Default: all Regions "
             "with a compute endpoint.",
    )
    p.add_argument(
        "-o", "--output", default=f"pcd_vm_inventory_{stamp}.csv",
        help="Output CSV path, or '-' for stdout. Default: %(default)s",
    )
    p.add_argument(
        "--include-metadata", action="store_true",
        help="Add the metadata column. Off by default because users can store "
             "arbitrary values, including secrets, in VM metadata.",
    )
    p.add_argument(
        "--no-fallback", action="store_true",
        help="Fail a Region instead of falling back to native APIs when a "
             "CQRS call fails.",
    )
    p.add_argument(
        "--skip-volumes", action="store_true",
        help="Do not call the volumes API. volume_total_gb is filled only "
             "from sizes embedded in CQRS VM records.",
    )
    p.add_argument(
        "--skip-floating-ips", action="store_true",
        help="Do not read floating IPs from native Neutron.",
    )
    p.add_argument(
        "--page-size", type=int, default=500,
        help="Items per page for paginated list calls. Default: %(default)s",
    )
    # Support diagnostic: saves raw CQRS responses, which contain user names,
    # email addresses, and error tracebacks. Hidden from --help.
    p.add_argument("--dump-cqrs", metavar="DIR", default=None, help=argparse.SUPPRESS)
    p.add_argument(
        "--os-profile", metavar="HMAC_KEY", default=None,
        help="Enable osprofiler distributed tracing with this HMAC key, for "
             "Platform9 support (PCD default: PF9_TRACE).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Debug logging. The log then includes API responses with VM "
             "details, user names, and email addresses; review it before "
             "sharing.",
    )
    args = p.parse_args(argv)
    args.region_filter = {r.strip() for r in args.regions.split(",") if r.strip()}
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    if args.verbose:
        LOG.warning("Debug logging is on. The log includes API responses with VM "
                    "details, user names, and email addresses; review it before sharing.")
    else:
        # openstacksdk and keystoneauth are noisy at INFO.
        logging.getLogger("openstack").setLevel(logging.WARNING)
        logging.getLogger("keystoneauth").setLevel(logging.WARNING)
    if args.dump_cqrs:
        LOG.warning("Saving raw CQRS responses to %s. They contain user names, email "
                    "addresses, and error details; delete them when done.", args.dump_cqrs)

    trace_id = enable_profiler(args.os_profile) if args.os_profile else None
    if trace_id:
        log_trace_id(trace_id)

    if not args.cloud and not os.environ.get("OS_CLOUD") and not os.environ.get("OS_AUTH_URL"):
        LOG.error("No credentials found. Pass --cloud <name> for a clouds.yaml entry, "
                  "or load your RC file into this shell first (source admin-openrc.sh).")
        return 1

    exported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    clouds = args.cloud or [None]
    columns = [c for c in COLUMNS if c != "metadata" or args.include_metadata]

    all_rows, all_failed, all_counts = [], [], {}
    for cloud in clouds:
        try:
            rows, failed, counts = export_cloud(cloud, args, exported_at)
        except Exception as exc:  # noqa: BLE001
            LOG.error("Export failed for %s: %s",
                      cloud or "environment credentials", describe_error(exc))
            return 1
        all_rows.extend(rows)
        all_failed.extend(failed)
        all_counts.update(counts)

    write_csv(all_rows, args.output, columns)

    LOG.info("Summary:")
    for (endpoint, region), (count, reported) in sorted(all_counts.items()):
        LOG.info("  %s / %s: %d VMs%s", endpoint, region, count, count_note(reported))
    sources = {}
    for row in all_rows:
        sources[row["data_source"]] = sources.get(row["data_source"], 0) + 1
    LOG.info("  Total: %d VMs (%s) -> %s", len(all_rows),
             ", ".join(f"{k}: {v}" for k, v in sorted(sources.items())) or "none",
             args.output)
    if trace_id:
        log_trace_id(trace_id)

    if all_failed:
        LOG.error("Partial inventory. Failed Regions: %s",
                  ", ".join(f"{e}/{r}" for e, r in all_failed))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
