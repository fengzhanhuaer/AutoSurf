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
    aliases: tuple[str, ...] = ()
    profile_path: str | None = None
    target_domain: str | None = None


# This catalog supplies stable names and known sign-in paths. Cookie signatures
# cover NexusPHP sites that are not listed here.
PT_SITE_CATALOG = (
    PtSiteDefinition("pt.hdupt.com", "HDU PT"),
    PtSiteDefinition("pterclub.net", "PterClub", aliases=("pterclub.com",)),
    PtSiteDefinition("52pt.site", "52PT", "/52bakatest0818.php"),
    PtSiteDefinition("u2.dmhy.org", "U2"),
    PtSiteDefinition("hdarea.club", "HDArea", "/"),
    PtSiteDefinition("hhanclub.net", "HhanClub", aliases=("hhan.club", "hhanclub.top")),
    PtSiteDefinition("tjupt.org", "TJUPT"),
    PtSiteDefinition("club.hares.top", "Hares", "/attendance.php?action=sign"),
    PtSiteDefinition("pt.btschool.club", "BTSchool", "/index.php?action=addbonus"),
    PtSiteDefinition("pttime.org", "PTTime"),
    PtSiteDefinition("ptchdbits.co", "CHDBits", "/bakatest.php"),
    PtSiteDefinition("hdcity.city", "HDCity", "/"),
    PtSiteDefinition("v6.nexushd.org", "NexusHD", "/signin.php", "custom_required"),
    PtSiteDefinition("rousi.pro", "Rousi", "/", "custom_required", aliases=("rousi.zip",)),
    PtSiteDefinition("kp.m-team.cc", "M-Team", "/", "custom_required"),
    PtSiteDefinition("totheglory.im", "TTG"),
    PtSiteDefinition(
        "zhuque.in", "Zhuque", "/", "profile_refresh_only", profile_path="/user/info",
    ),
    PtSiteDefinition("yemapt.org", "YemaPT"),
    PtSiteDefinition(
        "haidan.cc", "Haidan", "/", aliases=("haidan.video",),
        target_domain="www.haidan.cc",
    ),
    PtSiteDefinition("open.cd", "OpenCD", "/"),
    PtSiteDefinition("hdchina.org", "HDChina"),
    PtSiteDefinition("hdsky.me", "HDSky", "/"),
    PtSiteDefinition("hdvideo.top", "HDVideo", "/attendance.php"),
    PtSiteDefinition("nanyangpt.com", "NanyangPT", "/", "profile_refresh_only"),
    PtSiteDefinition("et8.org", "TCCF", "/", "profile_refresh_only"),
    PtSiteDefinition("pt.eastgame.org", "TLFBits", "/", "profile_refresh_only"),
    PtSiteDefinition("pt.keepfrds.com", "KEEPFRDS", "/", "profile_refresh_only"),
    PtSiteDefinition("ptlover.cc", "PTLover (不可用域名)", "/", "custom_required"),
)


@dataclass(frozen=True)
class PtDiscovery:
    site_key: str
    name: str
    url: str
    reason: str
    strategy: str
    profile_url: str | None = None

    @property
    def supported(self) -> bool:
        return self.sign_in_supported or self.profile_refresh_supported

    @property
    def sign_in_supported(self) -> bool:
        return self.strategy == "generic_browser"

    @property
    def profile_refresh_supported(self) -> bool:
        return self.strategy in {"generic_browser", "profile_refresh_only"}

    @property
    def default_sign_in_enabled(self) -> bool:
        return self.sign_in_supported

    @property
    def default_profile_refresh_enabled(self) -> bool:
        return self.strategy == "profile_refresh_only"


def discover_pt_site(domain: str, cookie_names: set[str] | frozenset[str]) -> PtDiscovery | None:
    normalized_domain = domain.lower().lstrip(".").rstrip(".")
    if not normalized_domain:
        return None

    definition = _site_definition(normalized_domain)
    lowered_names = {str(name).lower() for name in cookie_names}
    markers = lowered_names.intersection(PT_COOKIE_MARKERS)
    if definition:
        # Always navigate to the catalog's current domain. Alias credentials are
        # still merged into the same site, but retired domains are never used as
        # automation targets.
        target_domain = definition.target_domain or definition.domain
        return PtDiscovery(
            site_key=definition.domain,
            name=definition.name,
            url=urljoin(f"https://{target_domain}/", definition.signin_path.lstrip("/")),
            reason="site_catalog",
            strategy=definition.strategy,
            profile_url=(
                urljoin(f"https://{target_domain}/", definition.profile_path.lstrip("/"))
                if definition.profile_path else None
            ),
        )
    if markers:
        return PtDiscovery(
            site_key=canonical_pt_site_domain(normalized_domain),
            name=normalized_domain,
            url=f"https://{normalized_domain}/attendance.php",
            reason="cookie_signature",
            strategy="generic_browser",
        )
    return None


def canonical_pt_site_domain(domain: str) -> str:
    normalized = domain.lower().lstrip(".").rstrip(".")
    definition = _site_definition(normalized)
    if definition:
        return definition.domain
    return normalized[4:] if normalized.startswith("www.") else normalized


def pt_site_domain_aliases(domain: str) -> tuple[str, ...]:
    normalized = domain.lower().lstrip(".").rstrip(".")
    canonical = canonical_pt_site_domain(domain)
    definition = _site_definition(normalized)
    domains = [canonical, normalized[4:] if normalized.startswith("www.") else normalized]
    if definition:
        domains.extend((definition.domain, *definition.aliases))
    aliases = []
    for item in domains:
        aliases.extend((item, f"www.{item}"))
    return tuple(dict.fromkeys(aliases))


def _site_definition(domain: str) -> PtSiteDefinition | None:
    return next((
        item for item in PT_SITE_CATALOG
        if any(_domain_matches(domain, alias) for alias in (item.domain, *item.aliases))
    ), None)


def _domain_matches(credential_domain: str, catalog_domain: str) -> bool:
    return (
        credential_domain == catalog_domain
        or credential_domain.endswith(f".{catalog_domain}")
        or catalog_domain.endswith(f".{credential_domain}")
    )
