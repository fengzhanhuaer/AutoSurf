from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin


PT_COOKIE_MARKERS = frozenset({
    "c_secure_pass",
    "c_secure_ssl",
    "c_secure_tracker_ssl",
    "c_secure_uid",
    "nexusphp_a",
    "nexusphp_sid",
    "nexusphp_u",
    "passkey",
    "torrent_pass",
})


@dataclass(frozen=True)
class PtSiteDefinition:
    domain: str
    name: str
    signin_path: str = "/attendance.php"
    strategy: str = "generic_browser"


# This catalog supplies stable names and known sign-in paths. Cookie signatures
# cover NexusPHP sites that are not listed here.
PT_SITE_CATALOG = (
    PtSiteDefinition("pt.hdupt.com", "HDU PT"),
    PtSiteDefinition("pterclub.com", "PterClub"),
    PtSiteDefinition("52pt.site", "52PT"),
    PtSiteDefinition("u2.dmhy.org", "U2"),
    PtSiteDefinition("hdarea.club", "HDArea"),
    PtSiteDefinition("tjupt.org", "TJUPT"),
    PtSiteDefinition("club.hares.top", "Hares", "/attendance.php?action=sign"),
    PtSiteDefinition("pt.btschool.club", "BTSchool"),
    PtSiteDefinition("pttime.org", "PTTime"),
    PtSiteDefinition("ptchdbits.co", "CHDBits"),
    PtSiteDefinition("hdcity.city", "HDCity"),
    PtSiteDefinition("v6.nexushd.org", "NexusHD", "/signin.php", "custom_required"),
    PtSiteDefinition("rousi.pro", "Rousi", "/", "custom_required"),
    PtSiteDefinition("totheglory.im", "TTG"),
    PtSiteDefinition("zhuque.in", "Zhuque", "/", "custom_required"),
    PtSiteDefinition("yemapt.org", "YemaPT"),
    PtSiteDefinition("haidan.video", "Haidan", "/signin.php"),
    PtSiteDefinition("open.cd", "OpenCD"),
    PtSiteDefinition("hdchina.org", "HDChina"),
    PtSiteDefinition("hdsky.me", "HDSky"),
)


@dataclass(frozen=True)
class PtDiscovery:
    name: str
    url: str
    reason: str
    strategy: str

    @property
    def supported(self) -> bool:
        return self.strategy == "generic_browser"


def discover_pt_site(domain: str, cookie_names: set[str] | frozenset[str]) -> PtDiscovery | None:
    normalized_domain = domain.lower().lstrip(".").rstrip(".")
    if not normalized_domain:
        return None

    definition = next((item for item in PT_SITE_CATALOG if _domain_matches(normalized_domain, item.domain)), None)
    lowered_names = {str(name).lower() for name in cookie_names}
    markers = lowered_names.intersection(PT_COOKIE_MARKERS)
    if definition:
        target_domain = (
            definition.domain
            if definition.domain == normalized_domain or definition.domain.endswith(f".{normalized_domain}")
            else normalized_domain
        )
        return PtDiscovery(
            name=definition.name,
            url=urljoin(f"https://{target_domain}/", definition.signin_path.lstrip("/")),
            reason="site_catalog",
            strategy=definition.strategy,
        )
    if markers:
        return PtDiscovery(
            name=normalized_domain,
            url=f"https://{normalized_domain}/attendance.php",
            reason="cookie_signature",
            strategy="generic_browser",
        )
    return None


def _domain_matches(credential_domain: str, catalog_domain: str) -> bool:
    return (
        credential_domain == catalog_domain
        or credential_domain.endswith(f".{catalog_domain}")
        or catalog_domain.endswith(f".{credential_domain}")
    )
