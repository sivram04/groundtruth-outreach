"""Regression tests from the founder's review of the 30-lead sample, 2026-09-22.

Each case is the verified quotes the stored run holds for that lead, with the model's category.
Generic wording must not qualify a company; specific, supported project work must.
"""

import pytest

from outreach import research
from outreach.research import (COMMERCIAL_GENERIC as GEN, COMMERCIAL_PROJECT as CP, COMMERCIAL_SERVICE as CS,
                               QUALIFIED, RESIDENTIAL as RES, REVIEW_NEEDED)


def fit(*quotes):
    kept = research.downgrade_unsupported([{"category": c, "quote": q, "url": "u"} for c, q in quotes])
    return research.verdict(kept, pages_read=3)


# --- generic phrases never establish project work ----------------------------------------

@pytest.mark.parametrize("quote", [
    "CALL US FOR ALL YOUR RESIDENTIAL, COMMERCIAL, OR INDUSTRIAL ELECTRICAL PROJECTS AT 419-522-6616 !",
    "We specialize in all sizes of residential and commercial projects.",
    "From large-scale residential and commercial projects to service calls and Kohler Generator installation",
    "we provide reliable, high-quality electrical services for residential, commercial, and industrial projects.",
    "150 + Commercial Projects Done",
    "For commercial projects, we serve the full state of Ohio.",
    "We offer additional specialties to a wide range of businesses such as restaurants, multi-family housing, "
    "hospitals, retailers, office buildings and warehouses.",
    "As an Approved and State-Licensed Contractor, we serve many municipalities",
    "The services we offer include residential and commercial electrical repairs, service upgrades, "
    "plant equipment installation, and maintenance.",
])
def test_generic_commercial_wording_is_not_specific(quote):
    assert not research.is_specific(quote)
    assert research.downgrade_unsupported([{"category": CP, "quote": quote, "url": "u"}])[0]["category"] in (GEN, CS)


def test_b0039_alpine_is_review_needed():
    assert fit(
        (RES, "CALL US FOR ALL YOUR RESIDENTIAL, COMMERCIAL, OR INDUSTRIAL ELECTRICAL PROJECTS AT 419-522-6616 !"),
        (CP, "CALL US FOR ALL YOUR RESIDENTIAL, COMMERCIAL, OR INDUSTRIAL ELECTRICAL PROJECTS AT 419-522-6616 !"),
        (RES, "Whether you're looking to re-wire a portion of your home, or working on the wiring for a new one"),
        (CS, "Keep your commercial or industrial property running at maximum efficiency"),
        (CP, "New Construction"),
    )[0] == REVIEW_NEEDED


def test_b0145_rapid_is_review_needed():
    assert fit(
        (RES, "We service a wide variety of customers, both commercial and residential."),
        (CP, "We specialize in all sizes of residential and commercial projects."),
        (CP, "From large-scale residential and commercial projects to service calls and Kohler Generator installation"),
        (CS, "The services we offer include residential and commercial electrical repairs, service upgrades, "
             "plant equipment installation, and maintenance."),
        (RES, "Our electricians are experienced in installing generators for your emergency power needs."),
    )[0] == REVIEW_NEEDED


def test_a0143_waterworks_customer_list_is_review_needed():
    assert fit(
        (RES, "Residential Services We are a trusted, one-stop shop that provides vital repair, maintenance and "
              "installation services your home's plumbing, drain and HVAC systems."),
        (CP, "Commercial & Industrial Services We offer additional specialties to a wide range of businesses such as "
             "restaurants, multi-family housing, hospitals, retailers, office buildings and warehouses."),
        (CP, "Municipal Services As an Approved and State-Licensed Contractor, we serve many municipalities"),
        (CS, "Commercial HVAC Services Commercial HVAC Installation"),
    )[0] == REVIEW_NEEDED


def test_a0015_efficient_one_specific_quote_against_residential_is_review_needed():
    f, mix, why = fit(
        (CP, "Commercial Electrical Services Office and retail wiring, lighting maintenance, electrical "
             "troubleshooting, and tenant build-outs."),
        (CP, "we provide reliable, high-quality electrical services for residential, commercial, and industrial projects."),
        (RES, "Efficient Electric Corp. provides reliable and safe residential electrical services in Columbus"),
    )
    assert (f, mix) == (REVIEW_NEEDED, "MIXED") and "general terms" in why


def test_b0115_kouris_counts_of_projects_are_not_evidence():
    assert fit(
        (RES, "1000 + Residential Projects Done"),
        (CP, "150 + Commercial Projects Done"),
        (CP, "our specialization in electrical contracting sharpens our skills at everything from estimating and "
             "project management to wiring and installation."),
    )[0] == REVIEW_NEEDED


# --- specific, supported work still qualifies, mixed firms included -----------------------

def test_a0030_monroe_mixed_with_specific_work_stays_qualified():
    assert fit(
        (RES, "Monroe Plumbing installs and updates complete home plumbing systems"),
        (CP, "Reliable plumbing for businesses and contractors-new construction, tenant buildouts, restrooms"),
        (CP, "We collaborate with builders and GCs to map water, drain, and vent routes to the plan"),
    )[:2] == (QUALIFIED, "MIXED")


def test_a0062_conti_stays_qualified():
    assert fit(
        (CP, "The Conti Corporation specializes in heating and plumbing services for commercial, industrial, "
             "and institutional projects."),
        (CP, "The Conti Corporation portfolio includes schools, hospitals, sewage/wastewater treatment facilities, "
             "and churches throughout northeast Ohio and western Pennsylvania."),
    )[:2] == (QUALIFIED, "COMMERCIAL")


def test_a0280_reddy_stays_qualified():
    assert fit(
        (CP, "Commercial Office, retail, education and worship facilities - from tenant fit-outs to full building distribution."),
        (CP, "Hospitals CMH Reginal Cancer Center WILMINGTON, OH - New Building Construction"),
    )[0] == QUALIFIED


# --- a single project quote must explicitly establish the work (founder, 2026-09-22) -------

def test_a0188_current_systems_single_explicit_quote_stays_qualified():
    assert fit(
        (CP, "Commercial and industrial installation of electrical power equipment."),
        (CS, "We provide service and maintenance of existing power and lighting systems."),
        (CS, "Installation of fire alarm systems"),
    )[:2] == (QUALIFIED, "COMMERCIAL")


def test_a0250_langdon_bid_on_your_project_is_not_enough():
    f, mix, why = fit(
        (GEN, "Our experienced engineering and estimating departments are equipped to handle projects of any size."),
        (CP, "We look forward to the opportunity to bid on your project and demonstrate why Langdon, Inc. is a "
             "trusted name in sheet metal fabrication."),
        (GEN, "Industrial Solutions: Specialized ductwork for HVAC, Clean Room, Exhaust, Dust Collection, "
              "Air Pollution Control Systems and Welded Ductwork Systems."),
        (GEN, "providing a comprehensive range of solutions for both commercial and industrial applications."),
        (GEN, "Our spiral ductwork is available in convenient 5-foot lengths for smaller projects and 10-foot "
              "lengths for larger runs, ensuring easy shipping and installation."),
        (GEN, "Let us qualify for your next project!"),
    )
    # Since the batch-1 rule "bid" needs a commercial setting, so Langdon has no specific project
    # quote left; the verdict is still REVIEW_NEEDED.
    assert f == REVIEW_NEEDED


def test_b0100_heat_school_district_projects_is_not_enough():
    assert fit(
        (CP, "Over 75 School District Projects Completed"),
        (GEN, "helping businesses and schools districts in Ohio take control of their energy consumption and "
              "maintenance costs"),
        (GEN, "Our customers include: School Districts Colleges and Universities Commercial and Industrial Companies "
              "Government Entities Healthcare Organizations"),
        (CS, "Replacing interior/exterior lighting with energy efficient LED lamps and fixtures."),
        (CS, "Installing occupancy sensors to help manage temperature, lighting, humidity and CO2."),
        (CS, "Mechaincal retrofits including upgrades to Boilers, Pumps, Chillers, A/C Units and VFD Drives."),
    )[0] == REVIEW_NEEDED


def test_single_project_quote_supported_by_another_explicit_quote_qualifies():
    # "unless other verified evidence establishes the missing work"
    assert fit(
        (CP, "Over 75 School District Projects Completed"),
        (CS, "We install HVAC systems in commercial office buildings and hospitals."),
    )[0] == QUALIFIED


@pytest.mark.parametrize("quote,explicit", [
    ("Commercial and industrial installation of electrical power equipment.", True),
    ("Office and retail wiring, lighting maintenance, and tenant build-outs.", True),
    ("new construction for hospitals and schools", True),
    ("We look forward to the opportunity to bid on your project", False),
    ("Over 75 School District Projects Completed", False),
    ("Installing occupancy sensors to help manage temperature", False),
    ("residential and commercial installation", False),
])
def test_is_explicit(quote, explicit):
    assert research.is_explicit(quote) is explicit


# --- batch 1: construction words need a commercial setting; narrow subcontracting rule ----

def test_a0040_pattie_landscape_design_build_is_review_needed():
    f, _, _ = fit(
        (CP, "Our team handles everything-from design and permits to construction-ensuring a seamless experience "
             "and lasting results."),
        (CP, "The Design/Build Approach All of our design, horticulture and installation experts are on the same "
             "team assuring an enjoyable project that is completed on time and on budget"),
        (RES, "We create beautiful outdoor living spaces for your home."),
    )
    assert f == REVIEW_NEEDED


def test_a0021_halpin_construction_plumbing_is_review_needed():
    assert fit(
        (CP, "growing from a service-only company to service, excavation, and construction plumbing."),
        (CP, "New Construction And Commercial The last thing you ever want to worry about in owning a property is "
             "plumbing issues"),
        (RES, "We handle drain cleaning and water heaters for homeowners."),
    )[0] == REVIEW_NEEDED


CINFAB = [
    (CP, "We work as either a collaborative, cost-effective subcontractor to our mechanical contracting customers "
         "or as the prime sheet metal partner to a construction manager, general contractor or building owner"),
    (CP, "HVAC sheet metal design, fabrication and installation Design build and design assist capabilities"),
]


def test_a0059_cinfab_subcontractor_to_gcs_with_installation_stays_qualified():
    f, mix, why = fit(*CINFAB)
    assert (f, mix) == (QUALIFIED, "COMMERCIAL") and "subcontractor" in why


def test_subcontracting_without_construction_or_installation_work_is_not_enough():
    assert fit(
        (CP, "We work as a trusted subcontractor to general contractors across Ohio."),
        (CS, "Quality and safety are at the heart of everything we do."),
    )[0] == REVIEW_NEEDED


def test_subcontracting_statement_mentioning_homes_does_not_count():
    subs, _ = research.subcontracting_support(research.downgrade_unsupported([
        {"category": CP, "quote": "working with general contractors to bring new businesses or homes into the area",
         "url": "u"}]))
    assert subs == []


@pytest.mark.parametrize("quote,specific", [
    ("Our team handles everything-from design and permits to construction", False),
    ("The Design/Build Approach", False),
    ("commercial mechanical construction projects", True),
    ("Built for design-build. Ready for plan & spec.", True),
    ("Chase Bank GC: Rycon Construction", True),
    ("For commercial projects, we serve the full state of Ohio.", False),
    ("residential and commercial new construction", False),
    ("new construction for hospitals and residential builders", True),
])
def test_construction_words_need_a_commercial_setting(quote, specific):
    assert research.is_specific(quote) is specific


def test_a0112_design_build_and_plan_and_spec_are_specific():
    assert research.is_specific("Built for design-build. Ready for plan & spec.")


def test_residential_mention_needs_construction_activity():
    assert not research.is_specific("residential and industrial installation projects")
    assert research.is_specific("new construction for general contractors and residential builders")
