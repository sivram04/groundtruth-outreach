"""Stage 1: how far an email address can be checked without sending.

Outbound port 25 is blocked on GCP, so a mailbox cannot be asked whether it exists.
OK means nothing wrong was found; the bounce after a real send is the actual test.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import dns.exception
import dns.resolver
import requests

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_AGENT = "Mozilla/5.0 (compatible; LakshyaaOutreach/1.0)"

GENERIC_INBOXES = {
    "info", "office", "service", "services", "sales", "contact", "admin", "support", "hello",
    "estimating", "estimates", "bids", "bid", "accounting", "accounts", "ap", "ar", "billing",
    "hr", "jobs", "careers", "dispatch", "mail", "team", "customerservice", "webmaster",
    "noreply", "no-reply", "general", "inquiries", "inquiry", "frontdesk", "reception",
}
# Added 2026-09-22 after the spot-check found employment@edwards-elec.com marked OK:
# department and role mailboxes that do not reach the owner.
ROLE_INBOXES = {
    "employment", "hiring", "recruiting", "recruitment", "resumes", "resume", "apply",
    "orders", "order", "quotes", "quote", "marketing", "warranty", "warranties", "parts",
    "purchasing", "projects", "service.dept", "servicedept", "customer.service", "payroll",
    "invoices", "invoice", "receivables", "payables", "safety", "scheduling", "schedule",
}
GENERIC_INBOXES |= ROLE_INBOXES

# Personal and internet-provider mailboxes. A company may publish one of these as its real
# address; that is only accepted when the address is actually found on the company's site.
PERSONAL_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "aol.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "icloud.com", "me.com", "comcast.net", "att.net", "sbcglobal.net",
    "bellsouth.net", "verizon.net", "frontier.com", "windstream.net", "rr.com", "twc.com",
    "charter.net", "ameritech.net", "zoominternet.net", "wowway.com", "cox.net", "earthlink.net",
    "juno.com", "fuse.net", "embarqmail.com", "centurylink.net", "netzero.net", "roadrunner.com",
}

# Pages worth reading when looking for a published address.
CONTACT_LINK = re.compile(r"contact|about|team|staff|company|people|leadership|our-story", re.I)
MAX_PAGES = 6

# Answers that mean the server is there but refuses robots: the site exists.
BLOCKS_ROBOTS = {401, 403, 429}

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


def is_personal(email):
    return base_domain(domain_of_email(email)) in PERSONAL_MAIL


def _url(u):
    return u if "//" in u else f"http://{u}"


def _root(u):
    p = urlparse(_url(u))
    return f"{p.scheme}://{p.netloc}/"


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


def _get(url, attempts=3):
    """GET with retries: one dropped connection (seen 2026-09-22 as a passing SSLError on a
    working site) must not mark the site dead."""
    for i in range(attempts):
        try:
            return requests.get(url, timeout=12, allow_redirects=True, headers={"User-Agent": USER_AGENT})
        except requests.RequestException:
            if i == attempts - 1:
                raise
            time.sleep(1 + i)


def _status_loads(status):
    return status < 400 or status in BLOCKS_ROBOTS


def probe_website(url):
    """Returns (loads, detail). A 2xx/3xx answer loads. 401/403/429 means the server is up but
    refuses robots, which still proves the site exists. 404, 410, other 4xx and 5xx do not load.
    If the listed page is missing but the site's homepage answers, the site loads."""
    if not url:
        return False, "no website"
    target = _url(url)
    try:
        status = _get(target).status_code
    except requests.RequestException as e:
        return False, f"website does not answer: {url} ({type(e).__name__})"
    if _status_loads(status):
        return True, (f"website refuses automated reads (HTTP {status})" if status in BLOCKS_ROBOTS else "")
    root = _root(target)
    if root.rstrip("/") != target.rstrip("/") and 400 <= status < 500:
        try:
            root_status = _get(root).status_code
        except requests.RequestException:
            root_status = None
        if root_status is not None and _status_loads(root_status):
            return True, f"listed page returns HTTP {status}; homepage loads"
    return False, f"website returns HTTP {status}: {url}"


def _decode_cfemail(hexstr):
    key = int(hexstr[:2], 16)
    return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


# Things shaped like addresses that are not: retina image names (logo@2x.png), build strings,
# and form placeholders.
NOT_AN_ADDRESS_TLD = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "ico", "version", "avif"}
PLACEHOLDER_DOMAINS = {"domain.com", "email.com", "example.com", "yourdomain.com", "yoursite.com",
                       "sentry.io", "sentry-next.wixpress.com", "wixpress.com"}


def _real_address(e):
    domain = e.rsplit("@", 1)[-1]
    return domain.rsplit(".", 1)[-1] not in NOT_AN_ADDRESS_TLD and base_domain(domain) not in PLACEHOLDER_DOMAINS \
        and domain not in PLACEHOLDER_DOMAINS


def emails_in_page(html):
    """Every address visible in a page: plain text, mailto links, Cloudflare-protected
    addresses, and '[at]'/'[dot]' spellings. Image names and placeholders are dropped."""
    text = unquote(html)
    text = re.sub(r"\s*[\[(]\s*at\s*[\])]\s*", "@", text, flags=re.I)
    text = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", text, flags=re.I)
    found = {e.lower().rstrip(".") for e in EMAIL_IN_TEXT.findall(text)}
    for hexstr in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html):
        try:
            found.add(_decode_cfemail(hexstr).lower())
        except ValueError:
            pass
    return {e for e in found if _real_address(e)}


def _robots(root):
    rp = RobotFileParser()
    try:
        r = _get(urljoin(root, "/robots.txt"))
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
    except requests.RequestException:
        rp.parse([])
    return rp


def find_published(email, website):
    """Is `email` published on the company's own website? Reads the listed page, the homepage
    and up to MAX_PAGES same-site contact/about pages, honouring robots.txt.
    Returns (True, page_url) | (False, other addresses seen) | (None, why it could not be read)."""
    if not website:
        return None, "no website to read"
    start = _url(website)
    root = _root(start)
    host = base_domain(site_domain(start))
    robots = _robots(root)
    queue, seen, others, read_any = [start, root], set(), set(), False
    while queue and len(seen) < MAX_PAGES:
        page = queue.pop(0)
        if page in seen:
            continue
        seen.add(page)
        if not robots.can_fetch(USER_AGENT, page):
            continue
        try:
            r = _get(page)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        read_any = True
        found = emails_in_page(r.text)
        if email.lower() in found:
            return True, page
        others |= found
        for href in re.findall(r'href=["\']([^"\'#]+)', r.text):
            link = urljoin(page, href)
            if base_domain(site_domain(link)) == host and CONTACT_LINK.search(link) and link not in seen:
                queue.append(link)
    if not read_any:
        return None, "could not read the website"
    return False, ", ".join(sorted(others)) or "no addresses shown"


def lookups(leads):
    """Network lookups in parallel: mail servers per domain, one probe per website, and a
    site search for every personal mailbox."""
    domains = {domain_of_email(l["email"]) for l in leads if EMAIL_RE.match(l["email"])}
    sites = {l["website"] for l in leads if l["website"]}
    personal = {(l["email"].lower(), l["website"]) for l in leads
                if EMAIL_RE.match(l["email"]) and is_personal(l["email"])}
    with ThreadPoolExecutor(max_workers=12) as pool:
        mx = dict(zip(domains, pool.map(mail_servers, domains)))
        live = dict(zip(sites, pool.map(probe_website, sites)))
        published = dict(zip(personal, pool.map(lambda p: find_published(*p), personal)))
    return mx, live, published


def check(lead, first_seen, mx, live, published):
    """lead: {"id", "email", "website", "warning", "sent_by_hand"}.
    first_seen: {email_lower: lead_id} for addresses already claimed by an earlier row.
    live: {website: (loads, detail)}. published: {(email_lower, website): find_published result}.
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
    if is_personal(email):
        found, detail = published.get((key, lead["website"]), (None, "not searched"))
        if found:
            notes.append(f"personal mailbox ({domain}) found on the company's website: {detail}")
        elif found is False:
            reasons.append(f"personal mailbox ({domain}) not found on the company's website"
                           f" (site shows: {detail}); confirm it is theirs")
        else:
            reasons.append(f"personal mailbox ({domain}) could not be confirmed on the website ({detail})")
    elif site and base_domain(site) != base_domain(domain) and not lead["warning"]:
        reasons.append(f"email domain {domain} differs from website {site}")
    if email.split("@")[0].lower() in GENERIC_INBOXES:
        reasons.append("generic inbox, not a named person")
    loads, detail = live.get(lead["website"], (False, "website not checked")) if lead["website"] else (False, "no website")
    if not loads:
        reasons.append(detail)
    elif detail:
        notes.append(detail)
    if reasons:
        return RISKY, "; ".join(reasons + notes)
    return OK, "; ".join(["format valid, domain receives mail, website loads"] + notes)
