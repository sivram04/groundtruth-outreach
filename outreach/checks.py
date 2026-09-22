"""Stage 1: how far an email address can be checked without sending.

Outbound port 25 is blocked on GCP, so a mailbox cannot be asked whether it exists.
OK means nothing wrong was found; the bounce after a real send is the actual test.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import dns.exception
import dns.resolver
import requests

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")

GENERIC_INBOXES = {
    "info", "office", "service", "services", "sales", "contact", "admin", "support", "hello",
    "estimating", "estimates", "bids", "bid", "accounting", "accounts", "ap", "ar", "billing",
    "hr", "jobs", "careers", "dispatch", "mail", "team", "customerservice", "webmaster",
    "noreply", "no-reply", "general", "inquiries", "inquiry", "frontdesk", "reception",
}

# Personal and internet-provider mailboxes. Small trade owners often publish one of these on
# their own website; that is their real address, not a mismatch. Compared by base domain.
PERSONAL_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "aol.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "icloud.com", "me.com", "comcast.net", "att.net", "sbcglobal.net",
    "bellsouth.net", "verizon.net", "frontier.com", "windstream.net", "rr.com", "twc.com",
    "charter.net", "ameritech.net", "zoominternet.net", "wowway.com", "cox.net", "earthlink.net",
    "juno.com", "fuse.net", "embarqmail.com", "centurylink.net", "netzero.net", "roadrunner.com",
}
FROM_OWN_WEBSITE = "read from their website"

SENT_BY_HAND = "SENT BY HAND"
INVALID, DUPLICATE, RISKY, OK = "INVALID", "DUPLICATE", "RISKY", "OK"


def domain_of_email(email):
    return email.rsplit("@", 1)[-1].lower()


def site_domain(url):
    if not url:
        return ""
    host = urlparse(url if "//" in url else f"http://{url}").hostname or ""
    return host.lower().removeprefix("www.")


def base_domain(host):
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def mail_servers(domain, attempts=3):
    """True: the domain can receive mail (MX records, or an address record as implicit MX).
    False: it definitely cannot (domain does not exist, or a null MX says it takes no mail).
    None: could not find out (timeouts, failing name servers). Unknown is never invalid."""
    # Google Public DNS: the local and Cloud Run default resolvers timed out on some ISP
    # domains (neo.rr.com, 2026-09-22) that Google answers correctly.
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
    resolver.lifetime = 10
    for _ in range(attempts):
        try:
            answers = resolver.resolve(domain, "MX")
            return any(str(r.exchange) not in (".", "") for r in answers)
        except dns.resolver.NXDOMAIN:
            return False
        except dns.resolver.NoAnswer:
            try:
                resolver.resolve(domain, "A")
                return True
            except dns.resolver.NXDOMAIN:
                return False
            except dns.resolver.NoAnswer:
                return False
            except dns.exception.DNSException:
                continue
        except dns.exception.DNSException:
            continue
    return None


def website_loads(url):
    """Any HTTP answer below 500 counts as live (a 403 to robots is still a working site)."""
    if not url:
        return False
    target = url if "//" in url else f"http://{url}"
    try:
        r = requests.get(target, timeout=12, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; LakshyaaOutreach/1.0)"})
        return r.status_code < 500
    except requests.RequestException:
        return False


def lookups(leads):
    """Network lookups for every distinct domain and website, in parallel."""
    domains = {domain_of_email(l["email"]) for l in leads if EMAIL_RE.match(l["email"])}
    sites = {l["website"] for l in leads if l["website"]}
    with ThreadPoolExecutor(max_workers=12) as pool:
        mx = dict(zip(domains, pool.map(mail_servers, domains)))
        live = dict(zip(sites, pool.map(website_loads, sites)))
    return mx, live


def check(lead, first_seen, mx, live):
    """lead: {"id", "email", "website", "warning", "sent_by_hand", "source"}.
    first_seen: {email_lower: lead_id} for addresses already claimed by an earlier row.
    Returns (result, reason)."""
    email = lead["email"]
    if lead["sent_by_hand"]:
        return SENT_BY_HAND, lead["sent_by_hand"]
    if not email:
        return INVALID, "no email address"
    if not EMAIL_RE.match(email):
        return INVALID, f"not a valid address: {email}"
    key = email.lower()
    if key in first_seen and first_seen[key] != lead["id"]:
        return DUPLICATE, f"same address as {first_seen[key]}"
    domain = domain_of_email(email)
    receives = mx.get(domain)
    if receives is False:
        return INVALID, f"{domain} does not accept email (no mail servers, or it says it takes none)"

    reasons, notes = [], []
    if receives is None:
        reasons.append(f"could not check {domain}'s mail servers; recheck later")
    if lead["warning"]:
        reasons.append(f"Apollo warning: {lead['warning']}")
    site = site_domain(lead["website"])
    personal = base_domain(domain) in PERSONAL_MAIL
    if personal and lead.get("source") == FROM_OWN_WEBSITE:
        notes.append(f"personal mailbox ({domain}) published on the company's own website")
    elif site and base_domain(site) != base_domain(domain) and not lead["warning"]:
        reasons.append(f"email domain {domain} differs from website {site}")
    if email.split("@")[0].lower() in GENERIC_INBOXES:
        reasons.append("generic inbox, not a named person")
    if lead["website"] and not live.get(lead["website"], False):
        reasons.append(f"website does not load: {lead['website']}")
    elif not lead["website"]:
        reasons.append("no website")
    if reasons:
        return RISKY, "; ".join(reasons + notes)
    return OK, "; ".join(["format valid, domain receives mail, website loads"] + notes)
