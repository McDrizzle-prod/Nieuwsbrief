"""Weekoverzicht per mail, verstuurd via Laposta.

Elke vrijdag gaat er een mail naar de abonnees van de Laposta-lijst met de berichten die
sinds het vorige weekoverzicht zijn gevonden. De workflow maakt de campagne vrijdag in
het begin van de middag aan en plant hem in Laposta in voor 16:00 Nederlandse tijd.

Gebruik:
    python -m scraper.weekmail --modus gepland      # vanuit de vrijdagse workflow
    python -m scraper.weekmail --modus versturen    # nu versturen (één keer per week)
    python -m scraper.weekmail --modus test --testadres naam@voorbeeld.nl
    python -m scraper.weekmail --voorbeeld mail.html   # alleen opbouwen, niets versturen

De API-sleutel komt uit de omgevingsvariabele LAPOSTA_API_KEY (GitHub-secret). Welke
weken al zijn verstuurd, staat in data/weekmail.json.
"""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

from .run import ROOT, load_config
from .store import NL_TZ, load_json, save_json

API_BASIS = "https://api.laposta.nl/v2"
VERZENDUUR = 16           # vrijdag 16:00 Nederlandse tijd
VROEG_MINUTEN = 240       # vanaf 12:00 mag een geplande run de mail voor 16:00 inplannen
LAAT_MINUTEN = 180        # tot 19:00 wordt een vertraagde run nog direct verstuurd
MAX_LEEFTIJD_DAGEN = 14   # oudere berichten (bijv. van een nieuwe bron) niet meer mailen
LEVELS = {"hoog": 3, "middel": 2, "laag": 1, "geen": 0}
NL_MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
              "september", "oktober", "november", "december"]

KLEUR = {"inkt": "#15212a", "grijs": "#4b5965", "petrol": "#0a5d69", "lens": "#9a5200",
         "lens_vlak": "#fbf1e2", "lijn": "#d6dee3", "papier": "#f3f6f7"}
LETTER = "font-family:'Segoe UI',Arial,Helvetica,sans-serif;"


class LapostaFout(Exception):
    """De Laposta-API gaf een fout terug."""


# --- Laposta ---------------------------------------------------------------------

class Laposta:
    """Minimale client voor de campagne-API van Laposta (v2).

    Authenticatie: HTTP Basic met de API-sleutel als gebruikersnaam en een leeg
    wachtwoord. Parameters gaan als formulier (application/x-www-form-urlencoded).
    """

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.auth = (api_key, "")
        self.session = session or requests.Session()

    def _verzoek(self, methode: str, path: str, data: list[tuple[str, str]] | None = None) -> dict:
        resp = self.session.request(methode, f"{API_BASIS}/{path}", data=data, auth=self.auth, timeout=60)
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            detail = error.get("message") or resp.text[:300]
            if error.get("parameter"):
                detail += f" (parameter: {error['parameter']})"
            raise LapostaFout(f"Laposta-API gaf HTTP {resp.status_code}: {detail}")
        return body

    def campagnes(self) -> list[dict]:
        body = self._verzoek("GET", "campaign")
        return [c["campaign"] for c in body.get("data", []) if isinstance(c, dict) and c.get("campaign")]

    def maak_campagne(self, naam: str, onderwerp: str, afzender_naam: str, afzender_email: str,
                      lijst_id: str) -> str:
        body = self._verzoek("POST", "campaign", [
            ("type", "regular"),
            ("name", naam),
            ("subject", onderwerp),
            ("from[name]", afzender_naam),
            ("from[email]", afzender_email),
            ("list_ids[0]", lijst_id),
        ])
        try:
            return body["campaign"]["campaign_id"]
        except (KeyError, TypeError) as exc:
            raise LapostaFout(f"onverwacht antwoord bij aanmaken campagne: {body}") from exc

    def vul_inhoud(self, campagne_id: str, inhoud: str) -> None:
        self._verzoek("POST", f"campaign/{campagne_id}/content", [("html", inhoud)])

    def verstuur(self, campagne_id: str) -> None:
        self._verzoek("POST", f"campaign/{campagne_id}/action/send")

    def plan_in(self, campagne_id: str, moment: datetime) -> None:
        # ISO 8601 met expliciete tijdzone, zodat de tijdzone van het account niet uitmaakt.
        self._verzoek("POST", f"campaign/{campagne_id}/action/schedule",
                      [("delivery_requested", moment.isoformat(timespec="seconds"))])

    def testmail(self, campagne_id: str, email: str) -> None:
        self._verzoek("POST", f"campaign/{campagne_id}/action/testmail", [("email", email)])


# --- Tijdstip ---------------------------------------------------------------------

def tijdslot(nu: datetime) -> tuple[str, datetime | None, str]:
    """Wat doet een geplande run: inplannen voor 16:00, direct versturen of overslaan?

    De workflow draait op vrijdag om 12:40 en 13:40 UTC: in zomer- en wintertijd allebei
    vóór 16:00 Nederlandse tijd. De eerste run plant de mail in Laposta in voor 16:00; de
    tweede is een reserve voor als de eerste niet draait. Start een run door vertraging
    pas na 16:00, dan gaat de mail direct, tot uiterlijk drie uur later.
    Teruggegeven: (actie, verzendmoment bij inplannen, reden).
    """
    lokaal = nu.astimezone(NL_TZ)
    if lokaal.weekday() != 4:
        return "overslaan", None, "het is geen vrijdag"
    doel = lokaal.replace(hour=VERZENDUUR, minute=0, second=0, microsecond=0)
    minuten = (doel - lokaal).total_seconds() / 60
    if minuten > VROEG_MINUTEN:
        return "overslaan", None, f"te vroeg ({minuten:.0f} minuten voor {VERZENDUUR}:00)"
    if minuten > 5:
        return "inplannen", doel, f"ingepland voor {VERZENDUUR}:00"
    if minuten >= -LAAT_MINUTEN:
        return "nu", None, f"het is (bijna) {VERZENDUUR}:00 geweest; direct versturen"
    return "overslaan", None, f"verzendtijd ruim voorbij ({-minuten:.0f} minuten)"


# --- Inhoud -----------------------------------------------------------------------

def _tijd(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _niveau(item: dict) -> str:
    return (item.get("ai") or {}).get("moza_relevantie") or item.get("moza_level") or "laag"


def _sorteer(items: list[dict]) -> list[dict]:
    items = sorted(items, key=lambda i: i.get("date") or "", reverse=True)
    return sorted(items, key=lambda i: (LEVELS.get(_niveau(i), 1), i.get("score") or 0), reverse=True)


def berichten_sinds(items: list[dict], sinds: datetime, nu: datetime) -> list[dict]:
    """Berichten die na `sinds` zijn gevonden en niet ouder zijn dan twee weken."""
    grens = (nu.astimezone(NL_TZ).date() - timedelta(days=MAX_LEEFTIJD_DAGEN)).isoformat()
    return _sorteer([
        i for i in items
        if not i.get("baseline") and i.get("first_seen") and _tijd(i["first_seen"]) > sinds
        and (i.get("date") or "") >= grens
    ])


def week_info(dag: date) -> tuple[str, int, str]:
    jaar, week, _ = dag.isocalendar()
    maandag = date.fromisocalendar(jaar, week, 1)
    zondag = maandag + timedelta(days=6)

    def lang(d: date) -> str:
        return f"{d.day} {NL_MAANDEN[d.month - 1]} {d.year}"

    if maandag.year != zondag.year:
        bereik = f"{lang(maandag)} – {lang(zondag)}"
    elif maandag.month == zondag.month:
        bereik = f"{maandag.day} – {lang(zondag)}"
    else:
        bereik = f"{maandag.day} {NL_MAANDEN[maandag.month - 1]} – {lang(zondag)}"
    return f"{jaar}-{week:02d}", week, bereik


def _url(value: str) -> str:
    return value if value.startswith(("https://", "http://")) else "#"


def _kort(text: str, limit: int = 380) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + " …"


def _datum(value: str) -> str:
    d = date.fromisoformat(value[:10])
    return f"{d.day} {NL_MAANDEN[d.month - 1][:3]} {d.year}"


def _pages_url() -> str:
    """Adres van GitHub Pages voor deze repository, als `site_url` niet is ingevuld."""
    eigenaar, _, repo = os.environ.get("GITHUB_REPOSITORY", "mcdrizzle-prod/Nieuwsbrief").partition("/")
    return f"https://{eigenaar.lower()}.github.io/{repo}/"


def samenvatting(item: dict, onderwerpen: dict[str, str]) -> str:
    """Waar gaat het bericht over? AI-samenvatting, anders de tekst van de bron.

    Heeft de bron geen of alleen een heel korte beschrijving (zoals EUR-Lex of
    "Kamerstuk"), dan volgt uit de herkende zoektermen waar het bericht over gaat.
    """
    ai = (item.get("ai") or {}).get("samenvatting")
    if ai:
        return _kort(ai)
    bron = " ".join((item.get("summary") or "").split())
    fragment = " ".join((item.get("fragment") or "").split())
    tekst = bron if len(bron) >= 60 or not fragment else fragment
    if len(tekst) >= 60:
        return _kort(tekst)
    namen = [onderwerpen.get(t, t) for t in item.get("topics", [])]
    termen = list(dict.fromkeys(t for hits in (item.get("topic_hits") or {}).values() for t in hits))[:4]
    over = ""
    if namen:
        opsomming = namen[0] if len(namen) == 1 else ", ".join(namen[:-1]) + " en " + namen[-1]
        over = f"Gaat over {opsomming}" + (f" (herkend aan: {', '.join(termen)})." if termen else ".")
    if tekst and over:
        return f"{tekst.rstrip('.')}. {over}"
    return tekst or over


def moza_tekst(item: dict, themas: dict[str, dict]) -> str:
    """Wat betekent dit bericht voor MOZa? AI-duiding als die er is, anders de thema's."""
    ai = item.get("ai") or {}
    if ai.get("moza_toelichting"):
        return ai["moza_toelichting"]
    gevonden = [themas[m["thema"]] for m in item.get("moza", []) if m.get("thema") in themas]
    niveau = _niveau(item)
    if not gevonden:
        if "ebw" in item.get("topics", []):
            return (f"Relevantie voor MOZa: {niveau}. Gaat over het EBW-dossier in het algemeen: de afspraken over "
                    "business wallets waar MOZa mee te maken krijgt.")
        return (f"Relevantie voor MOZa: {niveau}. Geen direct raakvlak met een onderdeel van MOZa herkend; "
                "achtergrond bij het dossier.")
    namen = [t["naam"][0].lower() + t["naam"][1:] for t in gevonden]
    opsomming = namen[0] if len(namen) == 1 else ", ".join(namen[:-1]) + " en " + namen[-1]
    onderdelen = list(dict.fromkeys(o for t in gevonden for o in t.get("moza_onderdelen", [])))[:4]
    tekst = f"Relevantie voor MOZa: {niveau}. Raakt {opsomming}"
    return tekst + (f" ({', '.join(onderdelen)})." if onderdelen else ".")


SECTIES = [
    ("European Business Wallet", lambda i: i.get("category") != "nl-overheid" and "ebw" in i["topics"]),
    ("EUDI Wallet & eIDAS", lambda i: i.get("category") != "nl-overheid" and "ebw" not in i["topics"]
     and "eudi" in i["topics"]),
    ("Vertrouwensdiensten & standaarden", lambda i: i.get("category") != "nl-overheid"
     and "ebw" not in i["topics"] and "eudi" not in i["topics"]),
    ("Nederland", lambda i: i.get("category") == "nl-overheid"),
]


def maak_mail(items: list[dict], dag: date, cfg: dict, themas: dict[str, dict],
              onderwerpen: dict[str, str] | None = None) -> tuple[str, str]:
    """Onderwerp en HTML van het weekoverzicht."""
    onderwerpen = onderwerpen or {}
    sleutel, weeknummer, bereik = week_info(dag)
    site = (cfg.get("site_url") or _pages_url()).rstrip("/") + "/"
    editie = f"{site}#editie-{sleutel}"
    maximum = int(cfg.get("max_berichten", 25))
    getoond, rest = items[:maximum], items[maximum:]
    hoog = sum(1 for i in items if _niveau(i) == "hoog")
    aantal = f"{len(items)} {'bericht' if len(items) == 1 else 'berichten'}"
    onderwerp = (str(cfg.get("onderwerp") or "Walletbrief week {week}: {berichten}")
                 .replace("{week}", str(weeknummer)).replace("{aantal}", str(len(items)))
                 .replace("{berichten}", aantal))
    e = html.escape

    def p(stijl: str, inhoud: str) -> str:
        return f'<p style="margin:0 0 8px;{LETTER}{stijl}">{inhoud}</p>'

    def bericht(i: dict) -> str:
        tekst = samenvatting(i, onderwerpen)
        return (
            f'<div style="padding:14px 0;border-bottom:1px solid {KLEUR["lijn"]};">'
            + p(f"font-size:12px;color:{KLEUR['grijs']};", f"{e(i['source_name'])} · {e(_datum(i['date']))}")
            + p("font-size:17px;line-height:1.35;font-weight:bold;",
                f'<a href="{e(_url(i["url"]))}" style="color:{KLEUR["petrol"]};text-decoration:underline;">{e(i["title"])}</a>')
            + (p(f"font-size:15px;line-height:1.5;color:{KLEUR['inkt']};", e(tekst)) if tekst else "")
            + p(f"font-size:14px;line-height:1.5;color:{KLEUR['inkt']};background:{KLEUR['lens_vlak']};"
                f"border-left:3px solid {KLEUR['lens']};padding:8px 10px;margin:4px 0 0;",
                f'<strong style="color:{KLEUR["lens"]};">Wat betekent dit voor MOZa?</strong> {e(moza_tekst(i, themas))}')
            + "</div>"
        )

    blokken = []
    for titel, test in SECTIES:
        lijst = [i for i in getoond if test(i)]
        if not lijst:
            continue
        blokken.append(
            f'<h2 style="margin:24px 0 2px;{LETTER}font-size:18px;color:{KLEUR["inkt"]};'
            f'border-bottom:2px solid {KLEUR["inkt"]};padding-bottom:6px;">{e(titel)} ({len(lijst)})</h2>'
            + "".join(bericht(i) for i in lijst)
        )
    if not items:
        blokken.append(p(f"font-size:15px;color:{KLEUR['inkt']};", "Er zijn deze week geen nieuwe relevante berichten verschenen."))
    if rest:
        blokken.append(p(f"font-size:14px;color:{KLEUR['grijs']};margin-top:12px;",
                         f'En nog {len(rest)} andere berichten in de <a href="{e(editie)}" style="color:{KLEUR["petrol"]};">volledige nieuwsbrief</a>.'))

    knop = (f'<a href="{e(editie)}" style="display:inline-block;background:{KLEUR["petrol"]};color:#ffffff;'
            f'text-decoration:none;font-weight:bold;padding:10px 16px;border-radius:4px;font-size:14px;{LETTER}">'
            f"Lees de volledige nieuwsbrief van week {weeknummer}</a>")
    if items:
        intro = (f"{len(items)} {'nieuw bericht' if len(items) == 1 else 'nieuwe berichten'} uit officiële bronnen "
                 f"over de EUDI Wallet en de European Business Wallet"
                 + (f", waarvan {hoog} met hoge relevantie voor MijnOverheid Zakelijk." if hoog else ".")
                 + " Per bericht staat wat het betekent voor MOZa.")
        voorbode = (f"{len(items)} {'bericht' if len(items) == 1 else 'berichten'} over EUDI en EBW, "
                    "met wat ze betekenen voor MijnOverheid Zakelijk.")
    else:
        intro = voorbode = "Deze week zijn er geen nieuwe berichten over de EUDI Wallet en de European Business Wallet."

    inhoud = f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(onderwerp)}</title></head>
<body style="margin:0;padding:0;background:{KLEUR['papier']};">
<div style="display:none;max-height:0;overflow:hidden;">{e(voorbode)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{KLEUR['papier']};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;background:#ffffff;border:1px solid {KLEUR['lijn']};">
<tr><td style="padding:28px 32px 4px;">
{p(f"font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{KLEUR['grijs']};", "Walletbrief · weekoverzicht")}
<h1 style="margin:4px 0 10px;{LETTER}font-size:24px;line-height:1.25;color:{KLEUR['inkt']};">Week {weeknummer} · {e(bereik)}</h1>
{p(f"font-size:15px;line-height:1.5;color:{KLEUR['inkt']};", e(intro))}
<p style="margin:12px 0 4px;">{knop}</p>
</td></tr>
<tr><td style="padding:0 32px 8px;">
{''.join(blokken)}
</td></tr>
<tr><td style="padding:20px 32px 28px;border-top:1px solid {KLEUR['lijn']};">
{p(f"font-size:14px;color:{KLEUR['inkt']};", f'<a href="{e(editie)}" style="color:{KLEUR["petrol"]};">Lees de volledige nieuwsbrief van week {weeknummer}</a> · <a href="{e(site)}#archief" style="color:{KLEUR["petrol"]};">Archief</a>')}
{p(f"font-size:13px;line-height:1.5;color:{KLEUR['grijs']};", "Je ontvangt deze mail omdat je je hebt aangemeld voor het weekoverzicht van de Walletbrief. De berichten zijn automatisch verzameld uit officiële bronnen; gebruik altijd de originele bron als basis voor besluitvorming.")}
{p(f"font-size:13px;color:{KLEUR['grijs']};", f'<a href="/tag/unsubscribe" style="color:{KLEUR["grijs"]};">Afmelden voor dit weekoverzicht</a>')}
</td></tr>
</table>
</td></tr></table>
</body></html>
"""
    return onderwerp, inhoud


# --- Hoofdprogramma ----------------------------------------------------------------

def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _laposta_tijd(value: str | None, standaard: datetime) -> str:
    """Tijdstip uit Laposta ('2026-10-09 16:00:00', in de tijdzone van het account)."""
    try:
        moment = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return _utc(standaard)
    return _utc(moment if moment.tzinfo else moment.replace(tzinfo=NL_TZ))


def _samenvatting(regel: str) -> None:
    print(regel, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"### Weekoverzicht\n{regel}\n")


def main(argv: list[str] | None = None, root: str = ROOT, laposta: Laposta | None = None,
         klok=lambda: datetime.now(timezone.utc)) -> int:
    parser = argparse.ArgumentParser(description="Weekoverzicht per mail via Laposta")
    parser.add_argument("--modus", choices=["gepland", "versturen", "test"], default="versturen")
    parser.add_argument("--testadres", default="")
    parser.add_argument("--forceer", action="store_true", help="ook versturen als deze week al is verstuurd")
    parser.add_argument("--voorbeeld", help="alleen de mail opbouwen en als HTML opslaan in dit bestand")
    args = parser.parse_args(argv)

    config = load_config(os.path.join(root, "config"))
    cfg = config["notificaties"]
    themas = {t["id"]: t for t in config["onderwerpen"]["moza_themas"]}
    onderwerpen = {t["id"]: t["naam"] for t in config["onderwerpen"]["onderwerpen"]}
    data = load_json(os.path.join(root, "site", "data", "items.json"), {"items": []})
    items = data["items"]
    # Welke weken zijn verstuurd. Apart van data/state.json, zodat de dagelijkse run en
    # het weekoverzicht elkaar nooit in de weg zitten.
    status_file = os.path.join(root, "data", "weekmail.json")
    status = load_json(status_file, {})
    verstuurd = status.setdefault("verstuurd", {})

    nu = klok()
    lokaal = nu.astimezone(NL_TZ)
    sleutel, weeknummer, _ = week_info(lokaal.date())
    # Tot dit moment is gezocht. Wat later binnenkomt, gaat mee met de volgende mail.
    tot = _tijd(data.get("generated") or max((i["first_seen"] for i in items if i.get("first_seen")),
                                              default=_utc(nu)))
    doel = None

    if args.voorbeeld or args.modus == "test":
        selectie = berichten_sinds(items, nu - timedelta(days=7), nu) or _sorteer(
            [i for i in items if not i.get("baseline")])[:10]
    else:
        if not cfg.get("actief"):
            _samenvatting("Het weekoverzicht staat uit (`actief: false` in config/notificaties.yaml). Er is niets verstuurd.")
            return 0
        if args.modus == "gepland":
            actie, doel, reden = tijdslot(nu)
            if actie == "overslaan":
                _samenvatting(f"Deze run verstuurt geen weekoverzicht: {reden}.")
                return 0
        if sleutel in verstuurd and not args.forceer:
            _samenvatting(f"Het weekoverzicht van week {sleutel} is al verstuurd of ingepland; niets gedaan.")
            return 0
        # Alles wat sinds het vorige weekoverzicht is gevonden (bij --forceer: het
        # weekoverzicht van deze week opnieuw).
        laatste = max((_tijd(v["tot"]) for k, v in verstuurd.items() if k != sleutel and v.get("tot")),
                      default=nu - timedelta(days=7))
        selectie = berichten_sinds(items, laatste, nu)
        if not selectie and not cfg.get("ook_zonder_berichten"):
            _samenvatting(f"Geen nieuwe relevante berichten sinds het vorige weekoverzicht; week {sleutel} overgeslagen.")
            return 0

    onderwerp, inhoud = maak_mail(selectie, lokaal.date(), cfg, themas, onderwerpen)
    if args.voorbeeld:
        with open(args.voorbeeld, "w", encoding="utf-8") as fh:
            fh.write(inhoud)
        print(f"Voorbeeld opgeslagen in {args.voorbeeld}: '{onderwerp}' met {len(selectie)} berichten")
        return 0

    ontbreekt = [k for k in ("lijst_id", "afzender_email") if not cfg.get(k)]
    api_key = os.environ.get("LAPOSTA_API_KEY")
    if ontbreekt or not api_key:
        wat = ", ".join(ontbreekt + ([] if api_key else ["secret LAPOSTA_API_KEY"]))
        _samenvatting(f"Weekoverzicht niet verstuurd: vul eerst in: {wat} (zie LAPOSTA.md).")
        return 1
    if args.modus == "test" and "@" not in args.testadres:
        _samenvatting("Geef een geldig e-mailadres op voor de testmail.")
        return 1

    laposta = laposta or Laposta(api_key)
    naam = f"Walletbrief week {weeknummer} ({lokaal.year})"
    if args.modus == "test":
        naam += f" – test {lokaal:%d-%m %H:%M}"
    elif sleutel in verstuurd:
        naam += f" – opnieuw {lokaal:%d-%m %H:%M}"
    try:
        if args.modus != "test" and not args.forceer:
            # Tweede vangnet naast data/weekmail.json: als een eerdere run wel verstuurde
            # maar de status niet kon opslaan, staat de campagne al in Laposta.
            eerder = [c for c in laposta.campagnes() if c.get("name") == naam and c.get("delivery_requested")]
            if eerder:
                verstuurd[sleutel] = {"campagne_id": eerder[0].get("campaign_id"),
                                      "verzending": _laposta_tijd(eerder[0]["delivery_requested"], nu),
                                      "tot": _laposta_tijd(eerder[0].get("created"), tot),
                                      "berichten": None}
                save_json(status_file, status)
                _samenvatting(f"Het weekoverzicht van week {sleutel} staat in Laposta al als verstuurd of ingepland; "
                              "niets gedaan.")
                return 0
        campagne = laposta.maak_campagne(naam, onderwerp, cfg.get("afzender_naam") or "Walletbrief",
                                         cfg["afzender_email"], str(cfg["lijst_id"]))
        laposta.vul_inhoud(campagne, inhoud)
        if args.modus == "test":
            laposta.testmail(campagne, args.testadres)
            _samenvatting(f"Testmail '{onderwerp}' verstuurd naar {args.testadres}. "
                          f"De testcampagne staat als concept in Laposta.")
            return 0
        if doel:
            laposta.plan_in(campagne, doel)
        else:
            laposta.verstuur(campagne)
    except (LapostaFout, requests.RequestException) as exc:
        _samenvatting(f"Weekoverzicht niet verstuurd: {exc}")
        return 1

    verstuurd[sleutel] = {"campagne_id": campagne, "verzending": _utc(doel or nu), "tot": _utc(tot),
                          "berichten": len(selectie)}
    save_json(status_file, status)
    wanneer = f"ingepland voor vandaag {doel:%H:%M}" if doel else "verstuurd"
    _samenvatting(f"Weekoverzicht '{onderwerp}' {wanneer} ({len(selectie)} berichten, lijst {cfg['lijst_id']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
