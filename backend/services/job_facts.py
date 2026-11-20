"""Job facts by rules (no LLM, no network): plan §4 step ③ and the location part of §6.1.

`derive_facts(job, text)` fills category, workplace, countries / remote regions, pay,
seniority, experience, internship duration, visa sponsorship, start date and deadline.
Values the source gives win (marked "source"); otherwise conservative rules over title,
location and description (marked "rules"). A rule only sets a value when the text is
clear; anything unclear stays None (unknown).

`location_match` / `resolve_place` answer "is this job in a place I want?" with a small
built-in gazetteer of countries, major cities and US states.
"""
from __future__ import annotations

import re
from functools import lru_cache

from backend.job_schemas import NormalizedJob

FACT_KEYS = (
    "category", "workplace_type", "country_codes", "remote_regions", "compensation_type",
    "salary_min", "salary_max", "salary_currency", "salary_period", "seniority",
    "min_years_experience", "internship_duration", "visa_sponsorship", "start_date",
    "apply_deadline",
)

# ── Gazetteer ──────────────────────────────────────────────────────────────────

# ISO-2 code -> names / aliases (lowercase, matched case-insensitively on word boundaries).
_COUNTRIES: dict[str, list[str]] = {
    "US": ["united states", "united states of america", "u.s.a.", "u.s.", "usa"],
    "IN": ["india", "bharat"],
    "GB": ["united kingdom", "great britain", "britain", "england", "scotland", "wales",
           "northern ireland", "u.k."],
    "CA": ["canada"],
    "DE": ["germany", "deutschland"],
    "FR": ["france"],
    "NL": ["netherlands", "the netherlands", "holland"],
    "ES": ["spain", "españa"],
    "IT": ["italy", "italia"],
    "PT": ["portugal"],
    "IE": ["ireland"],
    "PL": ["poland", "polska"],
    "SE": ["sweden"],
    "NO": ["norway"],
    "DK": ["denmark"],
    "FI": ["finland"],
    "CH": ["switzerland"],
    "AT": ["austria"],
    "BE": ["belgium"],
    "LU": ["luxembourg"],
    "CZ": ["czech republic", "czechia"],
    "SK": ["slovakia"],
    "SI": ["slovenia"],
    "RO": ["romania"],
    "HU": ["hungary"],
    "GR": ["greece"],
    "BG": ["bulgaria"],
    "HR": ["croatia"],
    "RS": ["serbia"],
    "UA": ["ukraine"],
    "EE": ["estonia"],
    "LV": ["latvia"],
    "LT": ["lithuania"],
    "CY": ["cyprus"],
    "MT": ["malta"],
    "IS": ["iceland"],
    "TR": ["turkey", "türkiye", "turkiye"],
    "IL": ["israel"],
    "AE": ["united arab emirates", "u.a.e."],
    "SA": ["saudi arabia", "ksa"],
    "QA": ["qatar"],
    "BH": ["bahrain"],
    "KW": ["kuwait"],
    "OM": ["oman"],
    "EG": ["egypt"],
    "NG": ["nigeria"],
    "KE": ["kenya"],
    "ZA": ["south africa"],
    "MA": ["morocco"],
    "GH": ["ghana"],
    "TN": ["tunisia"],
    "AU": ["australia"],
    "NZ": ["new zealand"],
    "SG": ["singapore"],
    "JP": ["japan"],
    "KR": ["south korea", "korea", "republic of korea"],
    "CN": ["china", "mainland china"],
    "HK": ["hong kong"],
    "TW": ["taiwan"],
    "MY": ["malaysia"],
    "ID": ["indonesia"],
    "PH": ["philippines"],
    "VN": ["vietnam", "viet nam"],
    "TH": ["thailand"],
    "PK": ["pakistan"],
    "BD": ["bangladesh"],
    "LK": ["sri lanka"],
    "NP": ["nepal"],
    "BR": ["brazil", "brasil"],
    "MX": ["mexico", "méxico"],
    "AR": ["argentina"],
    "CL": ["chile"],
    "CO": ["colombia"],
    "PE": ["peru"],
    "UY": ["uruguay"],
    "CR": ["costa rica"],
    "EC": ["ecuador"],
    "RU": ["russia", "russian federation"],
    "AM": ["armenia"],
    "KZ": ["kazakhstan"],
}
# Uppercase codes that are safe to read case-sensitively anywhere ("US", not the pronoun "us").
_CS_COUNTRY_CODES = {"US": "US", "USA": "US", "UK": "GB", "UAE": "AE", "KSA": "SA"}

# canonical city -> (country, aliases)
_CITIES: dict[str, tuple[str, list[str]]] = {
    # India
    "bengaluru": ("IN", ["bangalore", "bengaluru urban"]),
    "hyderabad": ("IN", ["secunderabad"]),
    "pune": ("IN", []),
    "mumbai": ("IN", ["bombay", "navi mumbai"]),
    "delhi": ("IN", ["new delhi", "delhi ncr", "ncr"]),
    "gurugram": ("IN", ["gurgaon"]),
    "noida": ("IN", ["greater noida"]),
    "chennai": ("IN", ["madras"]),
    "kolkata": ("IN", ["calcutta"]),
    "ahmedabad": ("IN", []),
    "jaipur": ("IN", []),
    "kochi": ("IN", ["cochin"]),
    "thiruvananthapuram": ("IN", ["trivandrum"]),
    "chandigarh": ("IN", []),
    "mohali": ("IN", []),
    "indore": ("IN", []),
    "coimbatore": ("IN", []),
    "bhubaneswar": ("IN", []),
    "nagpur": ("IN", []),
    "lucknow": ("IN", []),
    "vadodara": ("IN", ["baroda"]),
    "surat": ("IN", []),
    "visakhapatnam": ("IN", ["vizag"]),
    "mysuru": ("IN", ["mysore"]),
    "faridabad": ("IN", []),
    "ghaziabad": ("IN", []),
    "thane": ("IN", []),
    "goa": ("IN", ["panaji"]),
    "bhopal": ("IN", []),
    "kanpur": ("IN", []),
    "patna": ("IN", []),
    "mangaluru": ("IN", ["mangalore"]),
    "vijayawada": ("IN", []),
    "dehradun": ("IN", []),
    # United States
    "new york": ("US", ["new york city", "nyc", "brooklyn", "manhattan"]),
    "san francisco": ("US", ["san francisco bay area", "sf bay area", "bay area"]),
    "san jose": ("US", []),
    "palo alto": ("US", []),
    "mountain view": ("US", []),
    "menlo park": ("US", []),
    "sunnyvale": ("US", []),
    "cupertino": ("US", []),
    "santa clara": ("US", []),
    "redwood city": ("US", []),
    "oakland": ("US", []),
    "seattle": ("US", []),
    "bellevue": ("US", []),
    "redmond": ("US", []),
    "austin": ("US", []),
    "boston": ("US", []),
    "chicago": ("US", []),
    "los angeles": ("US", []),
    "santa monica": ("US", []),
    "irvine": ("US", []),
    "san diego": ("US", []),
    "denver": ("US", []),
    "boulder": ("US", []),
    "atlanta": ("US", []),
    "miami": ("US", []),
    "dallas": ("US", []),
    "houston": ("US", []),
    "washington dc": ("US", ["washington, d.c.", "washington d.c.", "washington, dc"]),
    "philadelphia": ("US", []),
    "pittsburgh": ("US", []),
    "salt lake city": ("US", []),
    "phoenix": ("US", []),
    "minneapolis": ("US", []),
    "detroit": ("US", []),
    "raleigh": ("US", []),
    "nashville": ("US", []),
    "charlotte": ("US", []),
    "baltimore": ("US", []),
    "st. louis": ("US", ["saint louis", "st louis"]),
    "kansas city": ("US", []),
    "indianapolis": ("US", []),
    "portland": ("US", []),
    "jersey city": ("US", []),
    # Canada
    "toronto": ("CA", []),
    "vancouver": ("CA", []),
    "montreal": ("CA", ["montréal"]),
    "ottawa": ("CA", []),
    "calgary": ("CA", []),
    "waterloo": ("CA", []),
    "edmonton": ("CA", []),
    # UK & Ireland
    "london": ("GB", []),
    "manchester": ("GB", []),
    "edinburgh": ("GB", []),
    "bristol": ("GB", []),
    "leeds": ("GB", []),
    "glasgow": ("GB", []),
    "oxford": ("GB", []),
    "belfast": ("GB", []),
    "dublin": ("IE", []),
    "cork": ("IE", []),
    # Europe
    "berlin": ("DE", []),
    "munich": ("DE", ["münchen", "muenchen"]),
    "hamburg": ("DE", []),
    "frankfurt": ("DE", ["frankfurt am main"]),
    "cologne": ("DE", ["köln", "koeln"]),
    "stuttgart": ("DE", []),
    "düsseldorf": ("DE", ["dusseldorf", "duesseldorf"]),
    "paris": ("FR", []),
    "lyon": ("FR", []),
    "toulouse": ("FR", []),
    "amsterdam": ("NL", []),
    "rotterdam": ("NL", []),
    "the hague": ("NL", ["den haag"]),
    "utrecht": ("NL", []),
    "eindhoven": ("NL", []),
    "madrid": ("ES", []),
    "barcelona": ("ES", []),
    "lisbon": ("PT", ["lisboa"]),
    "porto": ("PT", []),
    "milan": ("IT", ["milano"]),
    "rome": ("IT", ["roma"]),
    "turin": ("IT", ["torino"]),
    "zurich": ("CH", ["zürich"]),
    "geneva": ("CH", ["genève"]),
    "basel": ("CH", []),
    "vienna": ("AT", ["wien"]),
    "brussels": ("BE", ["bruxelles"]),
    "copenhagen": ("DK", []),
    "stockholm": ("SE", []),
    "gothenburg": ("SE", ["göteborg"]),
    "oslo": ("NO", []),
    "helsinki": ("FI", []),
    "warsaw": ("PL", ["warszawa"]),
    "krakow": ("PL", ["kraków", "cracow"]),
    "wroclaw": ("PL", ["wrocław"]),
    "prague": ("CZ", ["praha"]),
    "budapest": ("HU", []),
    "bucharest": ("RO", []),
    "athens": ("GR", []),
    "tallinn": ("EE", []),
    "riga": ("LV", []),
    "vilnius": ("LT", []),
    "belgrade": ("RS", []),
    "kyiv": ("UA", ["kiev"]),
    "istanbul": ("TR", []),
    # Middle East & Africa
    "dubai": ("AE", []),
    "abu dhabi": ("AE", []),
    "riyadh": ("SA", []),
    "doha": ("QA", []),
    "tel aviv": ("IL", ["tel aviv-yafo"]),
    "cairo": ("EG", []),
    "lagos": ("NG", []),
    "nairobi": ("KE", []),
    "cape town": ("ZA", []),
    "johannesburg": ("ZA", []),
    # Asia-Pacific
    "tokyo": ("JP", []),
    "osaka": ("JP", []),
    "seoul": ("KR", []),
    "beijing": ("CN", []),
    "shanghai": ("CN", []),
    "shenzhen": ("CN", []),
    "taipei": ("TW", []),
    "sydney": ("AU", []),
    "melbourne": ("AU", []),
    "brisbane": ("AU", []),
    "auckland": ("NZ", []),
    "wellington": ("NZ", []),
    "kuala lumpur": ("MY", []),
    "jakarta": ("ID", []),
    "manila": ("PH", []),
    "ho chi minh city": ("VN", ["saigon"]),
    "hanoi": ("VN", []),
    "bangkok": ("TH", []),
    "karachi": ("PK", []),
    "lahore": ("PK", []),
    "islamabad": ("PK", []),
    "dhaka": ("BD", []),
    "colombo": ("LK", []),
    "kathmandu": ("NP", []),
    # Latin America
    "são paulo": ("BR", ["sao paulo"]),
    "rio de janeiro": ("BR", []),
    "mexico city": ("MX", ["ciudad de méxico", "cdmx"]),
    "guadalajara": ("MX", []),
    "buenos aires": ("AR", []),
    "santiago": ("CL", []),
    "bogotá": ("CO", ["bogota"]),
    "medellín": ("CO", ["medellin"]),
    "lima": ("PE", []),
    "montevideo": ("UY", []),
}

# Sub-national regions -> country (full names, matched case-insensitively).
# More places seen in real feeds (Arbeitnow lists bare town names, often in German/French).
# Added without touching the entries above; a canonical name already present is skipped.
_MORE_COUNTRY_NAMES: dict[str, list[str]] = {
    "DE": ["bundesrepublik deutschland", "allemagne", "duitsland"],
    "CH": ["schweiz", "suisse", "svizzera", "zwitserland"],
    "FR": ["frankreich", "frankrijk", "francia"],
    "AT": ["österreich", "oesterreich", "autriche"],
    "NL": ["nederland", "niederlande", "pays-bas"],
    "BE": ["belgique", "belgië", "belgien"],
    "ES": ["espana", "spanien", "espagne"],
    "IT": ["italien", "italie"],
    "PL": ["polen", "pologne"],
    "DK": ["danmark", "dänemark"],
    "SE": ["sverige", "schweden"],
    "NO": ["norge", "norwegen"],
    "GB": ["vereinigtes königreich", "royaume-uni"],
}
for _code, _names in _MORE_COUNTRY_NAMES.items():
    if _code in _COUNTRIES:
        _COUNTRIES[_code] = [*_COUNTRIES[_code], *(n for n in _names if n not in _COUNTRIES[_code])]

_MORE_CITIES: dict[str, tuple[str, list[str]]] = {
    # Germany
    "augsburg": ("DE", []), "hanover": ("DE", ["hannover"]), "leipzig": ("DE", []),
    "dresden": ("DE", []), "bonn": ("DE", []), "bremen": ("DE", []), "essen": ("DE", []),
    "dortmund": ("DE", []), "duisburg": ("DE", []), "bochum": ("DE", []), "wuppertal": ("DE", []),
    "mannheim": ("DE", []), "karlsruhe": ("DE", []), "nuremberg": ("DE", ["nürnberg", "nuernberg"]),
    "heidelberg": ("DE", []), "ulm": ("DE", []), "freiburg": ("DE", ["freiburg im breisgau"]),
    "kaiserslautern": ("DE", []), "böblingen": ("DE", ["boeblingen"]), "esslingen": ("DE", []),
    "passau": ("DE", []), "regensburg": ("DE", []), "ingolstadt": ("DE", []), "würzburg": ("DE", ["wuerzburg"]),
    "mainz": ("DE", []), "wiesbaden": ("DE", []), "darmstadt": ("DE", []), "kassel": ("DE", []),
    "münster": ("DE", ["muenster"]), "aachen": ("DE", []), "bielefeld": ("DE", []), "kiel": ("DE", []),
    "lübeck": ("DE", ["luebeck"]), "rostock": ("DE", []), "magdeburg": ("DE", []), "erfurt": ("DE", []),
    "jena": ("DE", []), "potsdam": ("DE", []), "braunschweig": ("DE", []), "osnabrück": ("DE", ["osnabrueck"]),
    "oldenburg": ("DE", []), "gelsenkirchen": ("DE", []), "bergisch gladbach": ("DE", []),
    "salzgitter": ("DE", []), "neumünster": ("DE", []), "detmold": ("DE", []), "wedel": ("DE", []),
    "gilching": ("DE", []), "markkleeberg": ("DE", []), "lünen": ("DE", []), "kronberg": ("DE", []),
    "düsseldorf": ("DE", ["duesseldorf", "dusseldorf"]), "leverkusen": ("DE", []),
    # Germany: states
    "bavaria": ("DE", ["bayern"]), "baden-württemberg": ("DE", ["baden-wuerttemberg", "baden-wurttemberg"]),
    "north rhine-westphalia": ("DE", ["nordrhein-westfalen", "nrw"]), "hesse": ("DE", ["hessen"]),
    "lower saxony": ("DE", ["niedersachsen"]), "saxony": ("DE", ["sachsen"]),
    "rhineland-palatinate": ("DE", ["rheinland-pfalz"]), "schleswig-holstein": ("DE", []),
    "thuringia": ("DE", ["thüringen"]), "brandenburg": ("DE", []),
    "mecklenburg-vorpommern": ("DE", []), "saarland": ("DE", []), "saxony-anhalt": ("DE", ["sachsen-anhalt"]),
    # Switzerland
    "bern": ("CH", ["berne"]), "lausanne": ("CH", []), "aarau": ("CH", []), "lucerne": ("CH", ["luzern"]),
    "winterthur": ("CH", []), "st. gallen": ("CH", ["st gallen", "sankt gallen"]), "lugano": ("CH", []),
    "mendrisio": ("CH", []), "zug": ("CH", []), "schwyz": ("CH", []), "solothurn": ("CH", []),
    "fribourg": ("CH", []), "neuchâtel": ("CH", ["neuchatel"]), "sion": ("CH", []), "biel": ("CH", ["bienne"]),
    "thun": ("CH", []), "moosseedorf": ("CH", []), "yverdon-les-bains": ("CH", []),
    "saint-sulpice": ("CH", []), "vaud": ("CH", ["waadt"]), "ticino": ("CH", ["tessin"]),
    "aargau": ("CH", []), "valais": ("CH", ["wallis"]),
    # France
    "bordeaux": ("FR", []), "strasbourg": ("FR", []), "nantes": ("FR", []), "lille": ("FR", []),
    "avignon": ("FR", []), "amiens": ("FR", []), "marseille": ("FR", []), "toulouse": ("FR", []),
    "montpellier": ("FR", []), "rennes": ("FR", []), "grenoble": ("FR", []), "cergy": ("FR", []),
    "meaux": ("FR", []), "clichy": ("FR", []), "melun": ("FR", []), "la garenne-colombes": ("FR", []),
    "nanterre": ("FR", []), "boulogne-billancourt": ("FR", []), "la défense": ("FR", ["la defense"]),
    "sophia antipolis": ("FR", []), "rouen": ("FR", []), "dijon": ("FR", []), "reims": ("FR", []),
    "île-de-france": ("FR", ["ile-de-france"]), "provence-alpes-côte d'azur": ("FR", ["paca"]),
    "auvergne-rhône-alpes": ("FR", []), "occitanie": ("FR", []), "nouvelle-aquitaine": ("FR", []),
    "hauts-de-france": ("FR", []), "grand est": ("FR", []), "bretagne": ("FR", ["brittany"]),
    "normandie": ("FR", ["normandy"]), "pays de la loire": ("FR", []),
    # Netherlands, Austria, others
    "zwolle": ("NL", []), "ijsselstein": ("NL", []), "utrecht": ("NL", []), "rotterdam": ("NL", []),
    "the hague": ("NL", ["den haag"]), "eindhoven": ("NL", []), "groningen": ("NL", []),
    "graz": ("AT", []), "linz": ("AT", []), "salzburg": ("AT", []), "innsbruck": ("AT", []),
    "antwerp": ("BE", ["antwerpen", "anvers"]), "ghent": ("BE", ["gent"]),
}
for _city, _entry in _MORE_CITIES.items():
    _CITIES.setdefault(_city, _entry)


_REGIONS_TO_COUNTRY: dict[str, str] = {
    **{s: "US" for s in [
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
        "delaware", "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
        "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
        "new jersey", "new mexico", "north carolina", "north dakota", "ohio", "oklahoma",
        "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington state",
        "west virginia", "wisconsin", "wyoming"]},
    **{s: "IN" for s in [
        "karnataka", "maharashtra", "telangana", "tamil nadu", "west bengal", "uttar pradesh",
        "haryana", "gujarat", "kerala", "rajasthan", "andhra pradesh", "madhya pradesh",
        "punjab", "odisha", "bihar", "uttarakhand"]},
    **{s: "CA" for s in ["ontario", "british columbia", "quebec", "québec", "alberta"]},
    **{s: "AU" for s in ["new south wales", "victoria, australia", "queensland"]},
}
_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
_CA_PROVINCE_CODES = {"ON", "BC", "QC", "AB", "MB", "NS", "SK"}

# Region tokens and what they cover.
_EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
       "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
_EUROPE = _EU | {"GB", "CH", "NO", "IS", "UA", "RS", "TR"}
_MIDDLE_EAST = {"AE", "SA", "QA", "BH", "KW", "OM", "IL", "EG"}
_AFRICA = {"NG", "KE", "ZA", "MA", "GH", "TN", "EG"}
_APAC = {"IN", "AU", "NZ", "SG", "JP", "KR", "CN", "HK", "TW", "MY", "ID", "PH", "VN",
         "TH", "PK", "BD", "LK", "NP"}
_LATAM = {"BR", "MX", "AR", "CL", "CO", "PE", "UY", "CR", "EC"}
REGION_MEMBERS: dict[str, set[str]] = {
    "EU": _EUROPE,  # job boards use "EU" loosely for Europe
    "EMEA": _EUROPE | _MIDDLE_EAST | _AFRICA,
    "APAC": _APAC,
    "LATAM": _LATAM,
}
_REGION_PHRASES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\b(?:worldwide|anywhere|global(?:ly)?|world ?wide|all countries|any location)\b", re.I), ["WORLDWIDE"]),
    (re.compile(r"\bemea\b", re.I), ["EMEA"]),
    (re.compile(r"\b(?:apac|asia[- ]pacific|asia)\b", re.I), ["APAC"]),
    (re.compile(r"\b(?:latam|latin america|south america|central america)\b", re.I), ["LATAM"]),
    (re.compile(r"\b(?:europe|european union|european)\b|(?-i:\bEU\b)", re.I), ["EU"]),
    (re.compile(r"\bnorth america\b", re.I), ["US", "CA"]),
    (re.compile(r"\b(?:americas|the americas)\b", re.I), ["US", "CA", "LATAM"]),
]


def _norm_place(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower().replace("’", "'"))


@lru_cache(maxsize=1)
def _gazetteer():
    """(name -> (country, city or None), compiled name regex, case-sensitive code regex)."""
    names: dict[str, tuple[str, str | None]] = {}
    for code, aliases in _COUNTRIES.items():
        for a in aliases:
            names[_norm_place(a)] = (code, None)
    for region, code in _REGIONS_TO_COUNTRY.items():
        names.setdefault(_norm_place(region), (code, None))
    for city, (code, aliases) in _CITIES.items():
        for a in [city, *aliases]:
            names[_norm_place(a)] = (code, city)
    alts = sorted(names, key=len, reverse=True)
    rx = re.compile(
        r"(?<![\w])(?:" + "|".join(re.escape(a) for a in alts) + r")(?![\w])", re.IGNORECASE
    )
    cs = re.compile(r"(?<![\w.])(?:" + "|".join(_CS_COUNTRY_CODES) + r")(?![\w])")
    return names, rx, cs


def country_name(code: str | None) -> str | None:
    """"IN" -> "India" (title-cased first name in the table), or None if unknown."""
    names = _COUNTRIES.get((code or "").upper())
    return names[0].title() if names else None


def _title(place: str) -> str:
    return " ".join(w if w.isupper() else w.capitalize() for w in place.split(",")[0].split())


def place_options() -> list[dict]:
    """Countries for a location picker: [{code, name, places}] sorted by name; `places` = the states
    and cities we know in that country (suggestions; any other place can be typed)."""
    out = []
    for code in _COUNTRIES:
        name = country_name(code)
        if not name:
            continue
        states = sorted({_title(r) for r, c in _REGIONS_TO_COUNTRY.items() if c == code})
        cities = sorted({_title(city) for city, (c, _aliases) in _CITIES.items() if c == code})
        out.append({"code": code, "name": name, "places": states + [x for x in cities if x not in states]})
    return sorted(out, key=lambda x: x["name"])


_ANYWHERE = re.compile(r"\b(?:anywhere|remote|worldwide)\b", re.IGNORECASE)


def place_check(place: str | None, location_text: str | None, country_codes: list[str] | None,
                workplace_type: str | None) -> str | None:
    """Is the job in the place you searched? "match" | "elsewhere" | "remote" | "unknown" (None: no
    place). `place` = "Karnataka, India", "Bengaluru, India" or "India". A state is matched by
    name in the job's location; a job naming another state (or city, or country) is elsewhere.
    Never excludes a job: Matches shows it so you can see where each job is."""
    if not place or not place.strip():
        return None
    loc = (location_text or "").strip()
    if workplace_type == "remote" or _ANYWHERE.search(loc):
        return "remote"
    code, city = resolve_place(place)
    job_code, job_city = resolve_place(loc) if loc else (None, None)
    job_code = job_code or next(iter(country_codes or []), None)
    if code and job_code and job_code != code:
        return "elsewhere"
    parts = [p.strip() for p in place.split(",") if p.strip()]
    if len(parts) < 2 and not city:  # a whole country
        return "match" if code and job_code == code else "unknown"
    area = _norm_place(parts[0])
    if re.search(r"(?<![\w])" + re.escape(area) + r"(?![\w])", _norm_place(loc)):
        return "match"
    if city:  # you searched a city
        if job_city:
            return "match" if job_city == city else "elsewhere"
        return "unknown"
    # you searched a state: elsewhere when the job names another known state or region of that country
    states = [r for r, c in _REGIONS_TO_COUNTRY.items() if c == code and r != area]
    if any(re.search(r"(?<![\w])" + re.escape(s) + r"(?![\w])", _norm_place(loc)) for s in states):
        return "elsewhere"
    return "unknown"


def resolve_place(name: str) -> tuple[str | None, str | None]:
    """"Bangalore" -> ("IN", "bengaluru"); "India" / "IN" -> ("IN", None); unknown -> (None, None)."""
    if not name or not name.strip():
        return None, None
    names, rx, _ = _gazetteer()
    n = _norm_place(name)
    if n in names:
        return names[n]
    up = name.strip().upper()
    if up in _CS_COUNTRY_CODES:
        return _CS_COUNTRY_CODES[up], None
    if up in _COUNTRIES:
        return up, None
    if up == "UK":
        return "GB", None
    # "Bengaluru, Karnataka, India" -> first known place (city preferred).
    hits = [names[_norm_place(m.group(0))] for m in rx.finditer(name)]
    for code, city in hits:
        if city:
            return code, city
    if hits:
        return hits[0]
    return None, None


def _places_in(text: str) -> tuple[list[str], list[str]]:
    """Country codes (ordered, deduped) and canonical cities mentioned in a location text."""
    if not text:
        return [], []
    names, rx, cs = _gazetteer()
    found: list[tuple[int, str, str | None]] = []
    for m in rx.finditer(text):
        code, city = names[_norm_place(m.group(0))]
        found.append((m.start(), code, city))
    for m in cs.finditer(text):
        found.append((m.start(), _CS_COUNTRY_CODES[m.group(0)], None))
    # ", CA" / ", NY" style codes after a place: a US state after a US (or unknown) place,
    # else a country code ("Pune, IN" is India, not Indiana).
    named = sorted(found)
    for m in re.finditer(r",\s*([A-Z]{2})\b(?!\.)", text):
        tok = m.group(1)
        segment_start = max(text.rfind(sep, 0, m.start()) for sep in (";", "|", "/", "\n"))
        prev = [f for f in named if segment_start < f[0] < m.start()]
        prev_country = prev[-1][1] if prev else None
        if prev_country and prev_country != "US":
            if tok in _COUNTRIES and tok != prev_country:
                found.append((m.start(1), tok, None))
            continue
        if tok in _US_STATE_CODES:
            found.append((m.start(1), "US", None))
        elif tok in _CA_PROVINCE_CODES:
            found.append((m.start(1), "CA", None))
        elif tok in _COUNTRIES:
            found.append((m.start(1), tok, None))
    found.sort(key=lambda f: f[0])
    countries: list[str] = []
    cities: list[str] = []
    for _, code, city in found:
        if code not in countries:
            countries.append(code)
        if city and city not in cities:
            cities.append(city)
    return countries, cities


# ── Small text helpers ─────────────────────────────────────────────────────────


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text or "", re.IGNORECASE))


# ── Category, workplace, seniority ─────────────────────────────────────────────

_INTERN_TITLE = r"\b(?:intern(?:ship)?s?|trainee|apprentice(?:ship)?|co-?op)\b"


def _category_from_title(title: str) -> str | None:
    if _has(_INTERN_TITLE, title):
        return "internship"
    if _has(r"\bpart[- ]time\b", title):
        return "part_time"
    if _has(r"\bfreelance(?:r)?\b", title):
        return "freelance"
    if _has(r"\bcontract(?:or)?\b|\bcontract[- ]to[- ]hire\b", title):
        return "contract"
    if _has(r"\bfull[- ]time\b|\bpermanent\b", title):
        return "full_time"
    return None


def _category_from_text(text: str) -> str | None:
    if _has(
        r"\binternships?\b(?! program(?:me)?s? for)|\bas an? intern\b|"
        r"\bintern(?:\s+(?:role|position|opportunity))\b|\b(?:summer|winter) intern\b",
        text,
    ) and not _has(r"\b(?:mentor|manage|supervise|work with|support) (?:our |the )?interns\b", text):
        return "internship"
    found = set()
    if _has(r"\bpart[- ]time\b", text):
        found.add("part_time")
    if _has(r"\bfreelanc(?:e|er|ing)\b", text):
        found.add("freelance")
    if _has(
        r"\bcontract (?:role|position|basis|job|assignment|engagement|opportunity)\b|"
        r"\bcontract[- ]to[- ]hire\b|\bfixed[- ]term contract\b|\bon a contract\b|"
        r"\b(?:\d+|six|twelve|three)[- ]months? contract\b|\bindependent contractor\b",
        text,
    ):
        found.add("contract")
    if _has(r"\bfull[- ]time\b|\bpermanent (?:role|position|job|contract)\b", text):
        found.add("full_time")
    return found.pop() if len(found) == 1 else None


_HYBRID_TEXT = re.compile(
    r"\bhybrid\b(?!\s*(?:cloud|apps?|mobile|search|retrieval|rag|infrastructure|architecture|"
    r"models?|approach|vehicles?|cars?|systems?|environments?|solutions?|deployments?|"
    r"integration|networks?|teams? of|methods?|algorithms?|work(?:loads|flows)))|"
    r"\b\d\s*(?:-\s*\d\s*)?days?\s+(?:a|per|each)\s+week\s+(?:in|at|from)\s+(?:the\s+|our\s+)?office\b",
    re.IGNORECASE,
)
_REMOTE_TEXT = re.compile(
    r"\b(?:fully remote|100% remote|remote[- ]first|work from home|work from anywhere|wfh|"
    r"remote (?:position|role|job|opportunity|internship|work(?:ing)?|only|ok|friendly|setup)|"
    r"(?:this|the) (?:role|position|job|internship) is (?:fully |100% )?remote|"
    r"work remotely|working remotely|completely remote|remote-based|is remote\b)",
    re.IGNORECASE,
)
_ONSITE_TEXT = re.compile(
    r"\b(?:on-?site|in[- ]office|in the office|work from (?:the )?office|wfo|in[- ]person)\b"
    r"(?!\s*(?:interviews?|days?|events?|gym|cafeteria|meals?|perks?|lunch|parking))",
    re.IGNORECASE,
)


def _workplace_from_short(s: str) -> str | None:
    """Location text or title: these are short, so plain words are clear enough."""
    if not s:
        return None
    if _has(r"\bhybrid\b", s):
        return "hybrid"
    if _has(r"\bremote\b|\bwork from home\b|\bwfh\b|\banywhere\b|\bworldwide\b", s):
        return "remote"
    if _has(r"\bon-?site\b|\bin[- ]office\b|\bin[- ]person\b", s):
        return "onsite"
    return None


def _workplace_from_text(text: str) -> str | None:
    if _HYBRID_TEXT.search(text):
        return "hybrid"
    remote = bool(_REMOTE_TEXT.search(text))
    onsite = bool(_ONSITE_TEXT.search(text))
    if remote and not onsite:
        return "remote"
    if onsite and not remote:
        return "onsite"
    return None


def _seniority_from_title(title: str) -> str | None:
    if _has(_INTERN_TITLE, title):
        return "intern"
    if _has(r"\b(?:lead|principal|staff|head|director|architect|vp|vice president|chief)\b", title):
        return "lead"
    if _has(r"\b(?:senior|sr\.?)\b|\bsnr\b", title):
        return "senior"
    if _has(r"\bmid[- ]?(?:level|senior)?\b|\bintermediate\b", title):
        return "mid"
    if _has(r"\b(?:junior|jr\.?|graduate|grad|entry[- ]level|entry|fresher|freshers|new grad|associate)\b", title):
        return "entry"
    return None


# ── Experience, duration, visa, dates ──────────────────────────────────────────

_YEARS_UNIT = r"(?:years?|yrs?\.?)"
_YEARS_PATTERNS = [
    re.compile(rf"(\d{{1,2}}(?:\.\d)?)\s*\+?\s*(?:-|–|—|to)\s*(\d{{1,2}})\s*\+?\s*{_YEARS_UNIT}", re.I),
    re.compile(rf"(?:at least|minimum(?: of)?|min\.?|over|more than|no less than)\s*(\d{{1,2}}(?:\.\d)?)\s*\+?\s*{_YEARS_UNIT}", re.I),
    re.compile(rf"(\d{{1,2}}(?:\.\d)?)\s*\+\s*{_YEARS_UNIT}", re.I),
    re.compile(rf"(\d{{1,2}}(?:\.\d)?)\s*{_YEARS_UNIT}", re.I),
]
_EXP_CONTEXT = re.compile(r"\bexp(?:erience|\.|\b)|\bworking\b|\bprofessional\b|\bindustry\b|\bhands-on\b|\bbackground\b", re.I)
_NOT_EXP = re.compile(
    r"^\s*(?:old|of age|in business|ago|of history|of operation|of (?:service|growth|innovation)|"
    r"track record|running|strong|in the making|warranty|contract|program|degree|course|"
    r"bachelor|of (?:study|college|university|schooling|education)|\s*(?:b\.?tech|degree))",
    re.I,
)
_EXP_AFTER = re.compile(
    r"^\s*(?:of\s+)?(?:with|in|using|building|developing|designing|working|writing|doing|leading|"
    r"as an?|hands-on|programming|coding)\b",
    re.I,
)
_NICE_LINE = re.compile(r"\b(?:preferred|preferably|nice to have|a plus|bonus|ideally)\b", re.I)


def _min_years(text: str) -> float | None:
    best: float | None = None
    for line in re.split(r"[\n;]|(?<=[.!?])\s+", text):
        if not re.search(r"\d", line) or _NICE_LINE.search(line):
            continue
        taken: list[tuple[int, int]] = []
        for pat in _YEARS_PATTERNS:
            for m in pat.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                after = line[m.end() : m.end() + 40]
                window = line[max(0, m.start() - 60) : m.end() + 60]
                if _NOT_EXP.match(after):
                    continue
                if not (_EXP_CONTEXT.search(window) or _EXP_AFTER.match(after)):
                    continue
                if re.search(r"\b(?:company|founded|since|we have been|we've been)\b", line[max(0, m.start() - 40) : m.start()], re.I):
                    continue
                taken.append((m.start(), m.end()))
                val = float(m.group(1))
                if val > 30:
                    continue
                best = val if best is None else min(best, val)
    if best is not None and best == int(best):
        best = float(int(best))
    return best


_DURATION = re.compile(
    r"(\d{1,2})\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?[- ]?\s*(months?|mos?\.?|weeks?|wks?)\b",
    re.I,
)
_DURATION_CONTEXT = re.compile(r"\b(?:intern(?:ship)?s?|duration|period|tenure|program(?:me)?|for a)\b", re.I)


def _internship_duration(text: str) -> str | None:
    for line in re.split(r"\n|(?<=[.!?])\s+", text):
        for m in _DURATION.finditer(line):
            window = line[max(0, m.start() - 60) : m.end() + 40]
            if not _DURATION_CONTEXT.search(window):
                continue
            if re.search(r"\b(?:within|after|probation|notice|every|ago|last|past)\b", line[max(0, m.start() - 25) : m.start()], re.I):
                continue
            unit = m.group(3).lower()
            unit = "weeks" if unit.startswith("w") else "months"
            a, b = int(m.group(1)), m.group(2)
            if a == 0 or a > 24:
                continue
            if b:
                return f"{a}-{int(b)} {unit}"
            return f"{a} {unit[:-1] if a == 1 else unit}"
    return None


_VISA_NO = re.compile(
    r"\bno (?:visa |work permit )?sponsorship\b|"
    r"\b(?:not|unable|cannot|can't|can not|won't|will not|do not|does not|don't)\b"
    r"(?:\s+(?:be|able|eligible|in a position|to|offer|provide|support|currently|any))*"
    r"\s+(?:visa\s+|work\s+)?sponsor|"
    r"\bwithout (?:the need for |requiring |needing )?(?:current or future |future )?(?:visa |employer |work )?sponsorship\b|"
    r"\bsponsorship (?:is )?not (?:available|offered|provided|possible)\b|\bnot sponsor(?:ing)?\b",
    re.I,
)
_VISA_YES = re.compile(
    r"\bvisa sponsorship (?:is )?(?:available|offered|provided|possible)\b|"
    r"\bwe (?:can |will |do |are able to |offer to )?sponsor (?:work |h-?1b |employment )?visas?\b|"
    r"\b(?:offer|provide|provides|offers|including|includes) (?:full )?(?:visa|relocation and visa|visa and relocation) "
    r"(?:sponsorship|support)\b|\bvisa sponsorship\s*:\s*(?:yes|available)\b|\bwill sponsor\b",
    re.I,
)


def _visa(text: str) -> str | None:
    if _VISA_NO.search(text):
        return "no"
    if _VISA_YES.search(text):
        return "yes"
    return None


def _start_date(text: str) -> str | None:
    m = re.search(r"\b(?:start(?:ing)? date|joining date|date of joining)\s*[:\-–]\s*([^\n;]{2,40})", text, re.I)
    if m:
        return m.group(1).strip().rstrip(".")
    if _has(r"\b(?:start(?:s)? immediately|immediate (?:start|joiners?|joining)|join immediately)\b", text):
        return "immediately"
    return None


def _apply_deadline(text: str) -> str | None:
    m = re.search(
        r"\b(?:apply by|application deadline|deadline to apply|deadline for applications|"
        r"last date (?:to|for) apply(?:ing)?|applications close(?: on)?|apply before)\s*[:\-–]?\s*([^\n;]{4,40})",
        text,
        re.I,
    )
    if not m:
        return None
    value = re.split(r"(?<=\d{4})|\.\s", m.group(1))[0].strip().rstrip(".,")
    return value or None


# ── Pay ────────────────────────────────────────────────────────────────────────

_CUR_SYMBOLS = {
    "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR",
    "$": "USD", "us$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP",
    "ca$": "CAD", "c$": "CAD", "cad": "CAD", "a$": "AUD", "au$": "AUD", "aud": "AUD",
    "s$": "SGD", "sgd": "SGD", "aed": "AED", "chf": "CHF",
}
_CUR = (
    r"(?:(?<![A-Za-z])(?:CA\$|C\$|AU\$|A\$|S\$|US\$|Rs\.?|INR|USD|EUR|GBP|CAD|AUD|SGD|AED|CHF|rupees)"
    r"|\$|₹|€|£)"
)
_NUM = (
    r"(?:\d{1,3}(?:,\d{2,3})+(?:\.\d+)?"  # 25,000 / 1,20,000 / 90,000.50
    r"|\d{1,3}(?:\.\d{3})+(?:,\d+)?"  # 50.000 (EU)
    r"|\d{1,3}(?:[   ]\d{3})+"  # 50 000
    r"|\d+(?:[.,]\d+)?)(?![\d])"
)
_MULT = r"(?:k|lakhs?|lacs?|lpa|l)(?![A-Za-z])"
_PERIOD = (
    r"(?:\s*(?:/|per|a|an)\s*(?P<per>month|mo|mth|year|yr|annum|hour|hr|week|wk|day)(?![A-Za-z])"
    r"|\s*(?P<per2>monthly|annually|yearly|hourly|weekly|daily|p\.\s?a\.?|pa|p\.\s?m\.?|pm)(?![A-Za-z])"
    r"|\s*(?P<lpa>lpa|l\.p\.a\.?|lakhs? per annum|lacs? per annum)(?![A-Za-z]))"
)
_MONEY = re.compile(
    rf"(?P<c1>{_CUR})?\s?(?P<n1>{_NUM})\s?(?P<m1>{_MULT})?\s?(?P<c1b>{_CUR}(?![A-Za-z]))?"
    rf"(?:\s*(?:-|–|—|to)\s*(?P<c2>{_CUR})?\s?(?P<n2>{_NUM})\s?(?P<m2>{_MULT})?\s?(?P<c2b>{_CUR}(?![A-Za-z]))?)?"
    rf"(?!\s?(?:m|mm|b|bn|million|billion|crores?|cr)(?![A-Za-z]))"
    rf"(?:{_PERIOD})?",
    re.IGNORECASE,
)
_PAY_CONTEXT = re.compile(
    r"\b(?:salary|salaries|pay|paid|compensation|stipend|ctc|base|range|ote|remuneration|package|"
    r"rate|wage|earn|per month|per annum|gross)\b",
    re.I,
)
_PERIOD_MAP = {
    "month": "month", "mo": "month", "mth": "month", "monthly": "month", "pm": "month",
    "year": "year", "yr": "year", "annum": "year", "annually": "year", "yearly": "year",
    "pa": "year",
    "hour": "hour", "hr": "hour", "hourly": "hour",
    "week": "week", "wk": "week", "weekly": "week",
    "day": "day", "daily": "day",
}


def _parse_num(s: str) -> float | None:
    s = s.replace(" ", " ").replace(" ", " ").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{2,3})+", s) else s.replace(",", ".")
    elif "." in s and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _mult(m: str) -> float:
    if m == "k":
        return 1000.0
    if m.startswith(("lakh", "lac", "lpa")) or m == "l":
        return 100000.0
    return 1.0


def _parse_salary(text: str) -> dict | None:
    """Best salary statement in the text -> {min, max, currency, period}; None if unclear."""
    best: tuple[int, dict] | None = None
    for m in _MONEY.finditer(text):
        n1 = _parse_num(m.group("n1"))
        n2 = _parse_num(m.group("n2")) if m.group("n2") else None
        if n1 is None:
            continue
        m1, m2 = (m.group("m1") or "").lower(), (m.group("m2") or "").lower()
        lpa = bool(m.group("lpa")) or "lpa" in (m1, m2)
        lakh = lpa or any(x.startswith(("lakh", "lac")) or x == "l" for x in (m1, m2))
        cur_tok = m.group("c1") or m.group("c1b") or m.group("c2") or m.group("c2b")
        if not cur_tok and not (lpa or any(x.startswith(("lakh", "lac")) for x in (m1, m2))):
            continue  # bare numbers ("3-5 years", "12 L") are not pay
        currency = "INR" if lakh else _CUR_SYMBOLS.get(cur_tok.lower().rstrip())
        if currency is None:
            continue
        # A multiplier written once applies to both ends: "$90-110k", "12-15 LPA".
        lo = n1 * _mult(m1 or m2)
        hi = n2 * _mult(m2 or m1) if n2 is not None else None
        if hi is not None and hi < lo:
            continue  # "₹10,000 - 5" style noise
        per_tok = (m.group("per") or m.group("per2") or "").lower().replace(".", "").replace(" ", "")
        period = "year" if lpa else _PERIOD_MAP.get(per_tok)
        before = text[max(0, m.start() - 60) : m.start()]
        context = before + " " + text[m.end() : m.end() + 40]
        if period is None:
            pm = re.match(
                r"\s*[(,]?\s*(?:per|a|/|each)\s*(month|year|annum|hour|week|day)|\s*[(,]?\s*(monthly|annually|yearly|hourly|weekly)",
                text[m.end() : m.end() + 30],
                re.I,
            )
            if pm:
                period = _PERIOD_MAP.get((pm.group(1) or pm.group(2)).lower())
        if period is None:
            top = hi or lo
            if currency == "INR":
                if top >= 300000:
                    period = "year"
                elif top >= 1000 and _has(r"\bstipend\b", context):
                    period = "month"
            elif top >= 20000:
                period = "year"
        if lo < 1 or (period == "hour" and lo > 1000):
            continue
        has_ctx = bool(_PAY_CONTEXT.search(context))
        score = (2 if hi is not None else 0) + (2 if period else 0) + (2 if has_ctx else 0) + (3 if lakh else 0)
        if score < 4 and not has_ctx and period is None:
            continue  # e.g. "$1,000 home office budget": nothing says it's pay
        cand = {"min": lo, "max": hi, "currency": currency, "period": period}
        if best is None or score > best[0]:
            best = (score, cand)
    return best[1] if best else None


_UNPAID = re.compile(
    r"\bunpaid (?:internship|position|role|opportunity|trainee)|\bthis (?:is an? )?unpaid\b|"
    r"\bno stipend\b|\bwithout (?:any )?stipend\b|\bvolunteer (?:position|role|opportunity|basis|internship)\b|"
    r"\bstipend\s*[:\-–]\s*(?:unpaid|none|nil|no|n/?a)\b|\b(?:internship|position|role) is unpaid\b",
    re.I,
)


# ── Main entry ─────────────────────────────────────────────────────────────────


def derive_facts(job: NormalizedJob, text: str) -> dict:
    """All rule-derived facts for one job. Source values win; unknown stays None."""
    text = text or ""
    title = job.title or ""
    loc = job.location_text or ""
    f: dict = {k: None for k in FACT_KEYS}
    f["country_codes"] = []
    f["remote_regions"] = []
    src: dict[str, str] = {}

    def put(key: str, value, origin: str) -> None:
        if value is None or value == [] or value == "":
            return
        f[key] = value
        src[key] = origin

    # Category
    if job.category:
        put("category", job.category, "source")
    else:
        put("category", _category_from_title(title) or _category_from_text(text), "rules")

    # Workplace
    if job.workplace_type:
        put("workplace_type", job.workplace_type, "source")
    elif job.is_remote is True:
        put("workplace_type", "remote", "source")
    else:
        put(
            "workplace_type",
            _workplace_from_short(loc) or _workplace_from_short(title) or _workplace_from_text(text),
            "rules",
        )

    # Countries and remote regions (from the location text, and the title for "Remote - US")
    countries, _cities = _places_in(loc)
    put("country_codes", countries, "rules")
    if f["workplace_type"] == "remote":
        regions: list[str] = []
        scope = loc + " | " + title
        for pat, toks in _REGION_PHRASES:
            if pat.search(scope):
                regions.extend(t for t in toks if t not in regions)
        if "WORLDWIDE" in regions:
            regions = ["WORLDWIDE"]
        else:
            t_countries, _ = _places_in(title)
            for c in countries + t_countries:
                if c not in regions:
                    regions.append(c)
        put("remote_regions", regions, "rules")

    # Pay
    if job.salary_min is not None or job.salary_max is not None:
        put("salary_min", job.salary_min, "source")
        put("salary_max", job.salary_max, "source")
        put("salary_currency", (job.salary_currency or "").upper() or None, "source")
        put("salary_period", job.salary_period, "source")
    else:
        sal = _parse_salary(text) or _parse_salary(title)
        if sal:
            put("salary_min", sal["min"], "rules")
            put("salary_max", sal["max"], "rules")
            put("salary_currency", sal["currency"], "rules")
            put("salary_period", sal["period"], "rules")
    has_salary = f["salary_min"] is not None or f["salary_max"] is not None
    if _UNPAID.search(text) or _UNPAID.search(title):
        put("compensation_type", "unpaid", "rules")
    elif _has(r"\bstipend\b", text) and (
        f["category"] == "internship"
        or _has(r"\bstipend\b\s*(?:of|is|amount|:|-|–)?\s*(?:₹|\$|€|£|rs\.?|inr|usd|\d)", text)
    ):
        put("compensation_type", "stipend", "rules")
    elif has_salary or _has(r"\bpaid internship\b|\bthis is a paid\b|\bfully paid\b", text):
        put("compensation_type", "paid", "rules")

    # Seniority
    sen = _seniority_from_title(title)
    if sen is None and f["category"] == "internship":
        sen = "intern"
    put("seniority", sen, "rules")

    # Experience, duration, visa, dates
    put("min_years_experience", _min_years(text), "rules")
    if f["category"] == "internship" or _has(r"\bduration\b", text):
        put("internship_duration", _internship_duration(text), "rules")
    put("visa_sponsorship", _visa(text), "rules")
    put("start_date", _start_date(text), "rules")
    put("apply_deadline", _apply_deadline(text), "rules")

    f["field_sources"] = src
    return f


# ── Location matching (search criteria, plan §6.1) ─────────────────────────────


def _region_covers(region: str, country: str) -> bool:
    if region == "WORLDWIDE" or region == country:
        return True
    return country in REGION_MEMBERS.get(region, set())


def location_match(
    wanted: list[str],
    country_codes: list[str],
    remote_regions: list[str],
    workplace_type: str | None,
    location_text: str | None,
) -> bool | None:
    """True = the job is in (or open to) a wanted place; False = clearly elsewhere;
    None = can't tell. `wanted` = [] means anywhere (True)."""
    if not wanted:
        return True
    want_countries: set[str] = set()
    want_cities: set[str] = set()
    want_regions: set[str] = set()
    for w in wanted:
        up = (w or "").strip().upper()
        if up in REGION_MEMBERS or up == "WORLDWIDE":
            want_regions.add(up)
            continue
        code, city = resolve_place(w)
        if city:
            want_cities.add(city)
        elif code:
            want_countries.add(code)
    if not (want_countries or want_cities or want_regions):
        return None
    city_countries = {_CITIES[c][0] for c in want_cities}
    all_wanted_countries = want_countries | city_countries

    def country_wanted(c: str) -> bool:
        return c in all_wanted_countries or any(_region_covers(r, c) for r in want_regions)

    job_countries, job_cities = _places_in(location_text or "")
    countries = list(dict.fromkeys([*country_codes, *job_countries]))

    if workplace_type == "remote":
        if not remote_regions or "WORLDWIDE" in remote_regions:
            return True
        for r in remote_regions:
            if r in want_regions:
                return True
            if any(_region_covers(r, c) for c in all_wanted_countries):
                return True
            if r in REGION_MEMBERS and any(REGION_MEMBERS[r] & REGION_MEMBERS.get(w, set()) for w in want_regions):
                return True
        return False

    if not countries and not job_cities:
        return None
    if job_cities and any(c in want_cities for c in job_cities):
        return True
    if any(c in want_countries or any(_region_covers(r, c) for r in want_regions) for c in countries):
        return True
    # Only cities wanted: same country but another (or unnamed) city.
    if any(c in city_countries for c in countries):
        return False if job_cities else None
    return False
