"""Language catalog: display names, text direction and CLDR plural categories.

Language codes are compared in a normalized form, so ``es-MX``, ``es_MX`` and
``es-mx`` all refer to the same language (iOS uses hyphens, Transifex uses
underscores).
"""

import re
from dataclasses import dataclass

PLURAL_ORDER = ("zero", "one", "two", "few", "many", "other")

_OTHER = ("other",)
_ONE_OTHER = ("one", "other")
_ONE_FEW_OTHER = ("one", "few", "other")
_ONE_MANY_OTHER = ("one", "many", "other")
_ONE_FEW_MANY_OTHER = ("one", "few", "many", "other")
_ALL = PLURAL_ORDER

# code -> (English name, native name, right-to-left, CLDR cardinal plural categories)
_LANGUAGES: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {
    "af": ("Afrikaans", "Afrikaans", False, _ONE_OTHER),
    "am": ("Amharic", "አማርኛ", False, _ONE_OTHER),
    "ar": ("Arabic", "العربية", True, _ALL),
    "az": ("Azerbaijani", "Azərbaycan", False, _ONE_OTHER),
    "be": ("Belarusian", "Беларуская", False, _ONE_FEW_MANY_OTHER),
    "bg": ("Bulgarian", "Български", False, _ONE_OTHER),
    "bn": ("Bengali", "বাংলা", False, _ONE_OTHER),
    "bs": ("Bosnian", "Bosanski", False, _ONE_FEW_OTHER),
    "ca": ("Catalan", "Català", False, _ONE_MANY_OTHER),
    "cs": ("Czech", "Čeština", False, _ONE_FEW_MANY_OTHER),
    "cy": ("Welsh", "Cymraeg", False, _ALL),
    "da": ("Danish", "Dansk", False, _ONE_OTHER),
    "de": ("German", "Deutsch", False, _ONE_OTHER),
    "el": ("Greek", "Ελληνικά", False, _ONE_OTHER),
    "en": ("English", "English", False, _ONE_OTHER),
    "es": ("Spanish", "Español", False, _ONE_MANY_OTHER),
    "et": ("Estonian", "Eesti", False, _ONE_OTHER),
    "eu": ("Basque", "Euskara", False, _ONE_OTHER),
    "fa": ("Persian", "فارسی", True, _ONE_OTHER),
    "fi": ("Finnish", "Suomi", False, _ONE_OTHER),
    "fil": ("Filipino", "Filipino", False, _ONE_OTHER),
    "fr": ("French", "Français", False, _ONE_MANY_OTHER),
    "ga": ("Irish", "Gaeilge", False, ("one", "two", "few", "many", "other")),
    "gl": ("Galician", "Galego", False, _ONE_OTHER),
    "gu": ("Gujarati", "ગુજરાતી", False, _ONE_OTHER),
    "he": ("Hebrew", "עברית", True, ("one", "two", "other")),
    "hi": ("Hindi", "हिन्दी", False, _ONE_OTHER),
    "hr": ("Croatian", "Hrvatski", False, _ONE_FEW_OTHER),
    "hu": ("Hungarian", "Magyar", False, _ONE_OTHER),
    "hy": ("Armenian", "Հայերեն", False, _ONE_OTHER),
    "id": ("Indonesian", "Bahasa Indonesia", False, _OTHER),
    "is": ("Icelandic", "Íslenska", False, _ONE_OTHER),
    "it": ("Italian", "Italiano", False, _ONE_MANY_OTHER),
    "ja": ("Japanese", "日本語", False, _OTHER),
    "ka": ("Georgian", "ქართული", False, _ONE_OTHER),
    "kk": ("Kazakh", "Қазақ тілі", False, _ONE_OTHER),
    "km": ("Khmer", "ខ្មែរ", False, _OTHER),
    "kn": ("Kannada", "ಕನ್ನಡ", False, _ONE_OTHER),
    "ko": ("Korean", "한국어", False, _OTHER),
    "lo": ("Lao", "ລາວ", False, _OTHER),
    "lt": ("Lithuanian", "Lietuvių", False, _ONE_FEW_MANY_OTHER),
    "lv": ("Latvian", "Latviešu", False, ("zero", "one", "other")),
    "mk": ("Macedonian", "Македонски", False, _ONE_OTHER),
    "ml": ("Malayalam", "മലയാളം", False, _ONE_OTHER),
    "mn": ("Mongolian", "Монгол", False, _ONE_OTHER),
    "mr": ("Marathi", "मराठी", False, _ONE_OTHER),
    "ms": ("Malay", "Bahasa Melayu", False, _OTHER),
    "my": ("Burmese", "မြန်မာ", False, _OTHER),
    "nb": ("Norwegian Bokmål", "Norsk bokmål", False, _ONE_OTHER),
    "ne": ("Nepali", "नेपाली", False, _ONE_OTHER),
    "nl": ("Dutch", "Nederlands", False, _ONE_OTHER),
    "nn": ("Norwegian Nynorsk", "Norsk nynorsk", False, _ONE_OTHER),
    "no": ("Norwegian", "Norsk", False, _ONE_OTHER),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ", False, _ONE_OTHER),
    "pl": ("Polish", "Polski", False, _ONE_FEW_MANY_OTHER),
    "ps": ("Pashto", "پښتو", True, _ONE_OTHER),
    "pt": ("Portuguese", "Português", False, _ONE_MANY_OTHER),
    "ro": ("Romanian", "Română", False, _ONE_FEW_OTHER),
    "ru": ("Russian", "Русский", False, _ONE_FEW_MANY_OTHER),
    "si": ("Sinhala", "සිංහල", False, _ONE_OTHER),
    "sk": ("Slovak", "Slovenčina", False, _ONE_FEW_MANY_OTHER),
    "sl": ("Slovenian", "Slovenščina", False, ("one", "two", "few", "other")),
    "sq": ("Albanian", "Shqip", False, _ONE_OTHER),
    "sr": ("Serbian", "Српски", False, _ONE_FEW_OTHER),
    "sv": ("Swedish", "Svenska", False, _ONE_OTHER),
    "sw": ("Swahili", "Kiswahili", False, _ONE_OTHER),
    "ta": ("Tamil", "தமிழ்", False, _ONE_OTHER),
    "te": ("Telugu", "తెలుగు", False, _ONE_OTHER),
    "th": ("Thai", "ไทย", False, _OTHER),
    "tr": ("Turkish", "Türkçe", False, _ONE_OTHER),
    "uk": ("Ukrainian", "Українська", False, _ONE_FEW_MANY_OTHER),
    "ur": ("Urdu", "اردو", True, _ONE_OTHER),
    "uz": ("Uzbek", "Oʻzbek", False, _ONE_OTHER),
    "vi": ("Vietnamese", "Tiếng Việt", False, _OTHER),
    "yi": ("Yiddish", "ייִדיש", True, _ONE_OTHER),
    "zh": ("Chinese", "中文", False, _OTHER),
    "zu": ("Zulu", "isiZulu", False, _ONE_OTHER),
}

# Regional / script variants that apps commonly ship: code -> (English name, native name)
_VARIANTS: dict[str, tuple[str, str]] = {
    "en-US": ("English (United States)", "English (US)"),
    "en-GB": ("English (United Kingdom)", "English (UK)"),
    "en-AU": ("English (Australia)", "English (Australia)"),
    "en-CA": ("English (Canada)", "English (Canada)"),
    "en-IN": ("English (India)", "English (India)"),
    "es-ES": ("Spanish (Spain)", "Español (España)"),
    "es-MX": ("Spanish (Mexico)", "Español (México)"),
    "es-US": ("Spanish (United States)", "Español (Estados Unidos)"),
    "es-419": ("Spanish (Latin America)", "Español (Latinoamérica)"),
    "es-AR": ("Spanish (Argentina)", "Español (Argentina)"),
    "es-CO": ("Spanish (Colombia)", "Español (Colombia)"),
    "fr-FR": ("French (France)", "Français (France)"),
    "fr-CA": ("French (Canada)", "Français (Canada)"),
    "de-DE": ("German (Germany)", "Deutsch (Deutschland)"),
    "de-AT": ("German (Austria)", "Deutsch (Österreich)"),
    "de-CH": ("German (Switzerland)", "Deutsch (Schweiz)"),
    "it-IT": ("Italian (Italy)", "Italiano (Italia)"),
    "nl-NL": ("Dutch (Netherlands)", "Nederlands (Nederland)"),
    "nl-BE": ("Dutch (Belgium)", "Nederlands (België)"),
    "pt-BR": ("Portuguese (Brazil)", "Português (Brasil)"),
    "pt-PT": ("Portuguese (Portugal)", "Português (Portugal)"),
    "zh-Hans": ("Chinese (Simplified)", "简体中文"),
    "zh-Hant": ("Chinese (Traditional)", "繁體中文"),
    "zh-CN": ("Chinese (China)", "中文（中国）"),
    "zh-TW": ("Chinese (Taiwan)", "中文（台灣）"),
    "zh-HK": ("Chinese (Hong Kong)", "中文（香港）"),
    "sr-Latn": ("Serbian (Latin)", "Srpski (latinica)"),
}


@dataclass(frozen=True)
class LocaleInfo:
    code: str
    name: str
    localized_name: str
    rtl: bool
    plural_categories: tuple[str, ...]


def normalize_code(code: str) -> str:
    """Normalize a language tag: ``es_mx`` -> ``es-MX``, ``zh_hans`` -> ``zh-Hans``."""
    parts = [p for p in re.split(r"[-_]", (code or "").strip()) if p]
    if not parts:
        return (code or "").strip()
    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            out.append(part.title())  # script
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            out.append(part.upper())  # region
        else:
            out.append(part)
    return "-".join(out)


_VALID_CODE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8})*$")


def is_valid_code(code: str) -> bool:
    """BCP 47-ish check: ``en``, ``es-MX``, ``zh_Hant``, ``es-419``, ``sr-Latn-RS``."""
    return bool(_VALID_CODE.match((code or "").strip()))


def code_key(code: str) -> str:
    """Comparison key for language codes (case and separator insensitive)."""
    return normalize_code(code).lower()


def same_code(a: str, b: str) -> bool:
    return code_key(a) == code_key(b)


def locale_info(code: str) -> LocaleInfo:
    norm = normalize_code(code)
    base = norm.split("-")[0]
    if base not in _LANGUAGES:
        return LocaleInfo(code=norm, name=norm, localized_name=norm, rtl=False, plural_categories=_ONE_OTHER)
    name, native, rtl, plurals = _LANGUAGES[base]
    if norm in _VARIANTS:
        name, native = _VARIANTS[norm]
    elif norm != base:
        suffix = norm[len(base) + 1:]
        name, native = f"{name} ({suffix})", f"{native} ({suffix})"
    return LocaleInfo(code=norm, name=name, localized_name=native, rtl=rtl, plural_categories=plurals)


def plural_categories(code: str) -> tuple[str, ...]:
    return locale_info(code).plural_categories


# CLDR added "many" to these languages for large round numbers (1 000 000);
# iOS falls back to "other" when it is missing, so translators may skip it.
_OPTIONAL_MANY = {"ca", "es", "fr", "it", "pt"}


def optional_categories(code: str) -> tuple[str, ...]:
    return ("many",) if normalize_code(code).split("-")[0] in _OPTIONAL_MANY else ()


def catalog() -> list[LocaleInfo]:
    """All known languages and variants, sorted by English name (for pickers)."""
    codes = list(_LANGUAGES) + list(_VARIANTS)
    return sorted((locale_info(c) for c in codes), key=lambda info: info.name)
