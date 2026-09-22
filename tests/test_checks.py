from outreach import checks

MX = {"airclaws.com": True, "af1hvac.com": True, "deadco.com": False}
LIVE = {"https://airclaws.com/": True, "https://airforceone.com/": True, "https://gone.com/": False}


def lead(**kw):
    base = {"id": "A-0001", "email": "ray@airclaws.com", "website": "https://airclaws.com/",
            "warning": "", "sent_by_hand": ""}
    return {**base, **kw}


def run(l, seen=None):
    return checks.check(l, seen or {}, MX, LIVE)


def test_ok():
    assert run(lead())[0] == checks.OK


def test_sent_by_hand_wins():
    assert run(lead(sent_by_hand="Sent email on 9/22/2026")) == (checks.SENT_BY_HAND, "Sent email on 9/22/2026")


def test_bad_format_and_missing():
    assert run(lead(email="ray@airclaws"))[0] == checks.INVALID
    assert run(lead(email=""))[0] == checks.INVALID


def test_duplicate_points_to_first():
    assert run(lead(id="B-0003"), {"ray@airclaws.com": "A-0001"}) == (checks.DUPLICATE, "same address as A-0001")
    assert run(lead(), {"ray@airclaws.com": "A-0001"})[0] == checks.OK  # the first row itself


def test_no_mail_servers_is_invalid():
    assert run(lead(email="bob@deadco.com", website=""))[0] == checks.INVALID


def test_unknown_mail_servers_is_risky_not_invalid():
    r, why = run(lead(email="bob@unknown.com", website=""))  # not in MX: lookup gave no answer
    assert r == checks.RISKY and "could not check" in why


def test_apollo_warning_is_risky_without_double_counting_domain():
    r, why = run(lead(email="freeman@af1hvac.com", website="https://airforceone.com/",
                      warning="MISMATCH: email domain af1hvac.com is not airforceone.com"))
    assert r == checks.RISKY and "Apollo warning" in why and "differs" not in why


def test_domain_mismatch_without_warning_is_risky():
    r, why = run(lead(email="freeman@af1hvac.com", website="https://airforceone.com/"))
    assert r == checks.RISKY and "differs from website" in why


def test_personal_mailbox_from_own_website_is_ok():
    MX["yahoo.com"] = True
    r, why = run(lead(email="john@yahoo.com", source="read from their website"))
    assert r == checks.OK and "personal mailbox" in why


def test_personal_mailbox_from_apollo_is_risky():
    r, why = run(lead(email="john@yahoo.com", source="Apollo, owner or founder"))
    assert r == checks.RISKY and "differs from website" in why


def test_generic_inbox_and_dead_site():
    r, why = run(lead(email="info@airclaws.com", website="https://gone.com/"))
    assert r == checks.RISKY and "generic inbox" in why and "does not load" in why


def test_subdomain_website_matches():
    assert run(lead(website="https://www.shop.airclaws.com"))[0] in (checks.OK, checks.RISKY)
    assert checks.base_domain(checks.site_domain("https://www.shop.airclaws.com")) == "airclaws.com"
