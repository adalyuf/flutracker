"""Utility functions for geographic data processing."""


def country_code_to_iso3(code_2: str) -> str | None:
    """Convert ISO 3166-1 alpha-2 to alpha-3 (for TopoJSON matching)."""
    mapping = {
        "AF": "AFG", "AL": "ALB", "DZ": "DZA", "AO": "AGO", "AR": "ARG",
        "AU": "AUS", "AT": "AUT", "BD": "BGD", "BE": "BEL", "BJ": "BEN",
        "BO": "BOL", "BR": "BRA", "BF": "BFA", "BI": "BDI", "KH": "KHM",
        "CM": "CMR", "CA": "CAN", "TD": "TCD", "CL": "CHL", "CN": "CHN",
        "CO": "COL", "CD": "COD", "CG": "COG", "CI": "CIV", "CU": "CUB",
        "CZ": "CZE", "DK": "DNK", "DO": "DOM", "EC": "ECU", "EG": "EGY",
        "SV": "SLV", "ET": "ETH", "FI": "FIN", "FR": "FRA", "DE": "DEU",
        "GH": "GHA", "GR": "GRC", "GT": "GTM", "GN": "GIN", "HT": "HTI",
        "HN": "HND", "HU": "HUN", "IN": "IND", "ID": "IDN", "IR": "IRN",
        "IQ": "IRQ", "IE": "IRL", "IL": "ISR", "IT": "ITA", "JP": "JPN",
        "JO": "JOR", "KZ": "KAZ", "KE": "KEN", "KP": "PRK", "KR": "KOR",
        "LB": "LBN", "LY": "LBY", "MG": "MDG", "MW": "MWI", "MY": "MYS",
        "ML": "MLI", "MX": "MEX", "MA": "MAR", "MZ": "MOZ", "MM": "MMR",
        "NP": "NPL", "NL": "NLD", "NZ": "NZL", "NE": "NER", "NG": "NGA",
        "NO": "NOR", "PK": "PAK", "PE": "PER", "PH": "PHL", "PL": "POL",
        "PT": "PRT", "RO": "ROU", "RU": "RUS", "RW": "RWA", "SA": "SAU",
        "SN": "SEN", "RS": "SRB", "SL": "SLE", "SG": "SGP", "SO": "SOM",
        "ZA": "ZAF", "SS": "SSD", "ES": "ESP", "LK": "LKA", "SD": "SDN",
        "SE": "SWE", "CH": "CHE", "SY": "SYR", "TW": "TWN", "TZ": "TZA",
        "TH": "THA", "TG": "TGO", "TN": "TUN", "TR": "TUR", "UG": "UGA",
        "UA": "UKR", "AE": "ARE", "GB": "GBR", "US": "USA", "UZ": "UZB",
        "VE": "VEN", "VN": "VNM", "YE": "YEM", "ZM": "ZMB", "ZW": "ZWE",
    }
    return mapping.get(code_2.upper())


def iso3_to_country_code(code_3: str) -> str | None:
    """Convert ISO 3166-1 alpha-3 to alpha-2."""
    # Build reverse mapping
    mapping = {v: k for k, v in _get_2to3().items()}
    return mapping.get(code_3.upper())


def _get_2to3():
    return {
        "AF": "AFG", "AL": "ALB", "DZ": "DZA", "AO": "AGO", "AR": "ARG",
        "AU": "AUS", "AT": "AUT", "BD": "BGD", "BE": "BEL", "BJ": "BEN",
        "BO": "BOL", "BR": "BRA", "BF": "BFA", "BI": "BDI", "KH": "KHM",
        "CM": "CMR", "CA": "CAN", "TD": "TCD", "CL": "CHL", "CN": "CHN",
        "CO": "COL", "CD": "COD", "CG": "COG", "CI": "CIV", "CU": "CUB",
        "CZ": "CZE", "DK": "DNK", "DO": "DOM", "EC": "ECU", "EG": "EGY",
        "SV": "SLV", "ET": "ETH", "FI": "FIN", "FR": "FRA", "DE": "DEU",
        "GH": "GHA", "GR": "GRC", "GT": "GTM", "GN": "GIN", "HT": "HTI",
        "HN": "HND", "HU": "HUN", "IN": "IND", "ID": "IDN", "IR": "IRN",
        "IQ": "IRQ", "IE": "IRL", "IL": "ISR", "IT": "ITA", "JP": "JPN",
        "JO": "JOR", "KZ": "KAZ", "KE": "KEN", "KP": "PRK", "KR": "KOR",
        "LB": "LBN", "LY": "LBY", "MG": "MDG", "MW": "MWI", "MY": "MYS",
        "ML": "MLI", "MX": "MEX", "MA": "MAR", "MZ": "MOZ", "MM": "MMR",
        "NP": "NPL", "NL": "NLD", "NZ": "NZL", "NE": "NER", "NG": "NGA",
        "NO": "NOR", "PK": "PAK", "PE": "PER", "PH": "PHL", "PL": "POL",
        "PT": "PRT", "RO": "ROU", "RU": "RUS", "RW": "RWA", "SA": "SAU",
        "SN": "SEN", "RS": "SRB", "SL": "SLE", "SG": "SGP", "SO": "SOM",
        "ZA": "ZAF", "SS": "SSD", "ES": "ESP", "LK": "LKA", "SD": "SDN",
        "SE": "SWE", "CH": "CHE", "SY": "SYR", "TW": "TWN", "TZ": "TZA",
        "TH": "THA", "TG": "TGO", "TN": "TUN", "TR": "TUR", "UG": "UGA",
        "UA": "UKR", "AE": "ARE", "GB": "GBR", "US": "USA", "UZ": "UZB",
        "VE": "VEN", "VN": "VNM", "YE": "YEM", "ZM": "ZMB", "ZW": "ZWE",
    }
