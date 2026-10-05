"""Optioneel: Nederlandse samenvatting en MOZa-duiding per bericht, gemaakt door Claude.

Deze stap draait alleen als ANTHROPIC_API_KEY is gezet (in GitHub: een repository
secret). Zonder sleutel werkt de nieuwsbrief gewoon, met de classificatie op
zoektermen. Per run worden hooguit AI_MAX_BERICHTEN berichten verwerkt (standaard 40),
in groepjes, zodat de kosten beperkt en voorspelbaar blijven.
"""

from __future__ import annotations

import json
import os

from .util import iso, now_utc

MODEL = os.environ.get("AI_MODEL") or "claude-opus-5-5"
GROEPSGROOTTE = 8
MAX_TEKST = 1500

SCHEMA = {
    "type": "object",
    "properties": {
        "berichten": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "samenvatting": {"type": "string"},
                    "moza_relevantie": {"type": "string", "enum": ["hoog", "middel", "laag", "geen"]},
                    "moza_toelichting": {"type": "string"},
                },
                "required": ["id", "samenvatting", "moza_relevantie", "moza_toelichting"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["berichten"],
    "additionalProperties": False,
}


def system_prompt(config: dict) -> str:
    moza = config["achtergrond"]["moza"]
    vragen = "\n".join(f"- {v['vraag']}: {' '.join(v['tekst'].split())}" for v in moza["kernvragen"])
    themas = "\n".join(f"- {t['naam']}: {' '.join(t['uitleg'].split())}"
                       for t in config["onderwerpen"]["moza_themas"])
    return f"""Je schrijft mee aan een Nederlandstalige nieuwsbrief voor mensen die werken aan
MijnOverheid Zakelijk (MOZa). De nieuwsbrief volgt officieel nieuws over de EU Digital
Identity Wallet (EUDI Wallet, eIDAS 2.0) en de European Business Wallet (EBW).

Over MOZa:
{' '.join(moza['inleiding'].split())}

Kernvragen voor MOZa:
{vragen}

Thema's waarop berichten MOZa kunnen raken:
{themas}

Je krijgt een lijst berichten (titel, bron, datum en een korte tekst, vaak in het Engels).
Geef voor elk bericht, met hetzelfde id:
- samenvatting: 2 tot 3 zinnen in helder Nederlands over wat er feitelijk is gebeurd of
  gepubliceerd. Baseer je alleen op de gegeven tekst; vul niets aan dat er niet staat.
  Als de tekst te mager is, zeg dat kort ("Alleen de titel is bekend: ...").
- moza_relevantie: hoog (raakt direct berichtenverkeer, inloggen/vertegenwoordiging,
  gegevensdeling of verplichtingen en planning voor overheden onder de EBW of EUDI),
  middel (relevante context, zoals standaarden, pilots of algemene voortgang), laag
  (zijdelings) of geen.
- moza_toelichting: 1 tot 2 zinnen over waarom dit voor MOZa telt en welk onderdeel het
  raakt (portaal/inloggen, Berichtenbox voor bedrijven, Notificatiedienst, Profielservice,
  roadmap). Formuleer als aandachtspunt, niet als vaststaand besluit. Leeg bij 'geen'."""


def _batch_payload(items: list[dict]) -> str:
    payload = [{
        "id": item["id"],
        "titel": item["title"],
        "bron": item["source_name"],
        "datum": item.get("date"),
        "tekst": " ".join(filter(None, [item.get("summary"), item.get("fragment")]))[:MAX_TEKST],
    } for item in items]
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _final_text(response) -> str:
    """Tekst van het model dat het antwoord afmaakte (na een eventuele fallback)."""
    parts: list[str] = []
    for block in response.content:
        if block.type == "fallback":
            parts = []
        elif block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def enrich_items(items: list[dict], config: dict, limit: int = 40) -> int:
    """Voegt item['ai'] toe aan berichten die dat nog niet hebben. Geeft het aantal terug."""
    if not os.environ.get("ANTHROPIC_API_KEY") or limit <= 0:
        return 0
    import anthropic  # pas laden als de stap echt draait

    todo = [i for i in items if "ai" not in i]
    todo.sort(key=lambda i: (i.get("date") or "", i.get("score", 0)), reverse=True)
    todo = todo[:limit]
    if not todo:
        return 0
    client = anthropic.Anthropic()
    system = [{"type": "text", "text": system_prompt(config), "cache_control": {"type": "ephemeral"}}]
    by_id = {i["id"]: i for i in todo}
    done = 0
    for start in range(0, len(todo), GROEPSGROOTTE):
        batch = todo[start:start + GROEPSGROOTTE]
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": _batch_payload(batch)}],
            )
        except anthropic.RateLimitError:
            print("  AI: limiet bereikt, rest volgt bij de volgende run", flush=True)
            break
        except anthropic.APIStatusError as exc:
            print(f"  AI: fout {exc.status_code}: {exc.message}", flush=True)
            if exc.status_code in (400, 401, 403, 404):
                break
            continue
        except anthropic.APIConnectionError as exc:
            print(f"  AI: verbindingsfout: {exc}", flush=True)
            continue
        if response.stop_reason in ("refusal", "max_tokens"):
            print(f"  AI: groep overgeslagen (stop_reason={response.stop_reason})", flush=True)
            continue
        try:
            results = json.loads(_final_text(response))["berichten"]
        except (ValueError, KeyError):
            print("  AI: antwoord kon niet worden gelezen", flush=True)
            continue
        stamp = iso(now_utc())
        for result in results:
            item = by_id.get(result.get("id"))
            if item is None:
                continue
            item["ai"] = {
                "samenvatting": result["samenvatting"].strip(),
                "moza_relevantie": result["moza_relevantie"],
                "moza_toelichting": result["moza_toelichting"].strip(),
                "model": response.model,
                "gemaakt": stamp,
            }
            done += 1
    print(f"  AI: {done} berichten voorzien van samenvatting en MOZa-duiding", flush=True)
    return done
