"""Demo scenarios: realistic cases built through the real services (POST /demo/scenarios).

So the staff dashboard and the partner pages look alive while Luka's unit 4b stays empty for the
live WhatsApp demo; Jona (unit 2a, student) has two closed self-help cases as history. No case is left open on Musterstraße's central boiler
(asset_boiler_1), so Luka's live report is never treated as a duplicate.

Older steps run with the demo clock shifted back (`_ago`), so timelines show realistic times.
No notify_tenant calls: nothing goes out on WhatsApp.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path

from . import rules, services
from .config import TZ, advance_clock, now, settings
from .partners.manifest import Manifest

DEMO_DIR = Path(settings.data_dir) / "demo"


@contextmanager
def _ago(**kw):
    delta = timedelta(**kw)
    advance_clock(-delta)
    try:
        yield
    finally:
        advance_clock(delta)


def _slot(day_offset: int, start_h: int, end_h: int, base: datetime | None = None) -> dict:
    day = (base or now()).date() + timedelta(days=day_offset)
    s = datetime.combine(day, time(start_h), tzinfo=TZ)
    e = datetime.combine(day, time(end_h), tzinfo=TZ)
    return {"start": s.isoformat(timespec="seconds"), "end": e.isoformat(timespec="seconds")}


def _chat(contact_id: str, case_id: str | None, lines: list[tuple[str, str]]) -> None:
    for direction, text in lines:
        services.log_message(contact_id, case_id, "whatsapp", direction, text)


def _consent_and_approve(case_id: str, contact_id: str, partner_id: str) -> None:
    """Consent → dispatch (stops at approval_pending under APPROVAL_POLICY=always) → staff approve."""
    fields = services.consent_fields_for(case_id, partner_id) or ["name", "phone", "address"]
    case = services.get_case(case_id)
    services.record_consent(contact_id, partner_id, case_id, fields,
                            f"On-site repair visit: {case.title or case.type}", "whatsapp")
    services.add_tenant_input(case_id, "tap: consent")
    try:
        services.dispatch_job(case_id, partner_id)
        return
    except rules.RuleViolation as rv:
        if rv.code != "approval_required":
            raise
    services.approve_case(case_id)


def _schedule(case_id: str, partner_id: str, tech_id: str, slots: list[dict], pick: int = 1,
              confirm: bool = True) -> None:
    services.partner_accept(case_id, partner_id)
    services.propose_slots(case_id, partner_id, slots, tech_id)
    services.confirm_slot(case_id, pick)
    if confirm:
        services.technician_confirm(case_id, tech_id)


def _free_slot(tech_id: str, partner_id: str, prefer: dict) -> dict:
    """prefer if free for that technician, else their first free slot (real calendar)."""
    free = next(t["free_slots"] for t in services.get_technicians(partner_id) if t["tech_id"] == tech_id)
    return prefer if prefer in free else free[0]


def _pdf(lines: list[str]) -> bytes:
    """Tiny one-page PDF (Helvetica), no extra dependencies."""
    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    text = "BT /F1 11 Tf 50 790 Td 15 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    body = text.encode("cp1252", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


# --------------------------------------------------------------------------- scenarios

def s1_approval_pending() -> str:
    """Sofia, Lothringerstr. 41: Viessmann no flame (F4), diagnosis 85%, waiting for staff approval."""
    with _ago(minutes=42):
        c = services.open_case(
            "c_207", "repair.heating", "urgent", "No heating and no hot water since this morning",
            "Boiler display shows F4, all radiators cold", "F4", "asset_boiler_41", trade="heating",
            diagnosis={"cause_id": "boiler_fault", "confidence": 0.85,
                       "reasoning": "Display shows F4 (no flame signal). All radiators and taps are cold, "
                                    "but the gas stove works, so the gas supply is fine.",
                       "questions_asked": [{"question": "Are all radiators cold, or only some?", "answer": "All of them"},
                                           {"question": "Does your gas stove still work?", "answer": "Yes"}]})
        _chat("c_207", c.id, [
            ("in", "Hi, my heating and hot water stopped this morning. The boiler shows F4."),
            ("out", "Sorry to hear that, Sofia. Are all the radiators cold, or only some?"),
            ("in", "All of them, the whole flat is freezing"),
            ("out", "Thanks. Does your gas stove still work?"),
            ("in", "Yes it does"),
        ])
        services.add_tenant_input(c.id, "voice note")
        services.add_tenant_input(c.id, "tap: All cold")
    with _ago(minutes=38):
        services.rank_partners(c.id)
        _chat("c_207", c.id, [("out", "That points to the boiler's ignition (no flame signal, F4). May I share your "
                                      "name, phone, address and photos with Heizung Schmidt GmbH?"),
                              ("in", "Yes, go ahead")])
        services.record_consent("c_207", "heizung-schmidt", c.id, ["name", "phone", "address", "photos"],
                                "heating repair visit", "whatsapp")
        try:
            services.dispatch_job(c.id, "heizung-schmidt")
        except rules.RuleViolation:
            pass
        _chat("c_207", c.id, [("out", "Thanks! The property management just needs to approve the job, "
                                      "then it goes straight to Heizung Schmidt GmbH.")])
    return c.id


def s2_requested() -> str:
    """Aylin, Musterstr. 1a: leak under the kitchen sink → Heizung Schmidt (plumbing), awaiting accept."""
    with _ago(hours=3, minutes=10):
        c = services.open_case(
            "c_204", "repair.plumbing", "normal", "Water leaking under the kitchen sink",
            "Steady drip from a pipe joint, cabinet floor wet", None, None, trade="plumbing",
            diagnosis={"cause_id": "frozen_or_damaged_pipe", "confidence": 0.7,
                       "reasoning": "Steady drip at a joint under the sink; the shut-off valve stops it, "
                                    "so it's a damaged pipe or loose joint, not the tap.",
                       "questions_asked": [{"question": "Is the water coming from the tap or from below?", "answer": "From the pipe below"},
                                           {"question": "Does it stop when you close the valve under the sink?", "answer": "Yes"}]})
        _chat("c_204", c.id, [
            ("in", "Hello, there's water dripping under my kitchen sink, the cabinet is all wet 😕"),
            ("out", "Thanks Aylin. Is it coming from the tap or from the pipe below?"),
            ("in", "From the pipe below"),
            ("out", "Please close the little valve under the sink. Does the dripping stop?"),
            ("in", "Yes it stopped"),
            ("out", "Great, that keeps it safe for now. May I share your details with Heizung Schmidt GmbH (plumbing)?"),
        ])
    with _ago(hours=2, minutes=55):
        _chat("c_204", c.id, [("in", "Yes please")])
        _consent_and_approve(c.id, "c_204", "heizung-schmidt")
    return c.id


def s3_awaiting_technician() -> str:
    """Grace, Musterstr. 3c: shower mixer cartridge → Ali proposed, tenant picked, waiting for Ali."""
    with _ago(hours=20):
        c = services.open_case(
            "c_206", "repair.plumbing", "normal", "Shower only lukewarm, sinks are hot",
            "Shower never gets hot, kitchen and bathroom sink are hot", None, None, trade="plumbing",
            diagnosis={"cause_id": "shower_mixer_faulty", "confidence": 0.85,
                       "reasoning": "Only the shower is cold while the sinks are hot and the radiators work: "
                                    "the thermostatic cartridge in the shower mixer is the likely cause.",
                       "questions_asked": [{"question": "Is it only the shower, or the sinks too?", "answer": "Only the shower"},
                                           {"question": "Are the radiators warm?", "answer": "Yes"}]})
        _chat("c_206", c.id, [
            ("in", "Hi! My shower only gets lukewarm since yesterday"),
            ("out", "Hi Grace! Is it only the shower, or are the sinks cold too?"),
            ("in", "Only the shower, the sinks are hot"),
            ("out", "Then it's most likely the shower mixer cartridge, a quick job for a plumber. "
                    "May I share your details with Heizung Schmidt GmbH?"),
            ("in", "Sure"),
        ])
        _consent_and_approve(c.id, "c_206", "heizung-schmidt")
    slots = [_free_slot("tech_ali", "heizung-schmidt", _slot(1, 10, 12)), _slot(2, 14, 16)]
    _schedule(c.id, "heizung-schmidt", "tech_ali", slots, pick=1, confirm=False)
    case = services.get_case(c.id)
    label = (case.data or {}).get("proposed_slots", [{}])[0].get("label", "tomorrow")
    _chat("c_206", c.id, [("out", f"Heizung Schmidt GmbH can send Ali Yilmaz. Which time works for you?"),
                          ("in", label),
                          ("out", "Great, I've asked Ali to confirm, I'll let you know in a moment.")])
    return c.id


def s4_scheduled_electrical() -> str:
    """Mateusz, Musterstr. 3b: electric instant heater → Elektro Klein, Marco confirmed tomorrow 10–12."""
    with _ago(hours=27):
        c = services.open_case(
            "c_205", "repair.electrical", "normal", "No hot water from the electric water heater",
            "Display on the heater is dark, fuse looks fine", None, "asset_heater_3b", trade="electrical",
            diagnosis={"cause_id": "electric_instant_heater", "confidence": 0.8,
                       "reasoning": "The flat's hot water comes from an electric instant heater; its display is dark "
                                    "although the fuse is on, so the heater or its power supply is faulty.",
                       "questions_asked": [{"question": "Is the display on the water heater lit?", "answer": "No, it's dark"},
                                           {"question": "Is the fuse for the heater switched on?", "answer": "Yes"}]})
        _chat("c_205", c.id, [
            ("in", "Hey, no hot water at all. The little heater in the bathroom is dead"),
            ("out", "Hi Mateusz, is the display on the water heater lit?"),
            ("in", "No, completely dark. Fuse is on"),
            ("out", "Thanks, that needs an electrician. May I share your details with Elektro Klein?"),
            ("in", "Yes"),
        ])
        _consent_and_approve(c.id, "c_205", "elektro-klein")
    slot = _free_slot("tech_marco", "elektro-klein", _slot(1, 10, 12))
    _schedule(c.id, "elektro-klein", "tech_marco", [slot, _slot(2, 8, 10)], pick=1, confirm=True)
    label = (services.get_case(c.id).data or {}).get("proposed_slots", [{}])[0].get("label", "tomorrow")
    from app.agent import flow  # the reminder is real (sent at 18:00 the day before / on skip-to-tomorrow)

    reminded = flow.schedule_reminder(c.id, slot, ["c_205"], who="Marco Klein from Elektro Klein")
    _chat("c_205", c.id, [("in", label),
                          ("out", f"Perfect, Mateusz! Marco Klein from Elektro Klein will come on {label}."
                                  + (" I'll remind you the evening before 👍" if reminded else " 👍"))])
    return c.id


async def s5_closed_invoiced() -> str:
    """Hannah, Lothringerstr. 41: circulation pump replaced 5 days ago, invoice + report on the unit."""
    with _ago(days=6, hours=3):
        c = services.open_case(
            "c_209", "repair.heating", "urgent", "Radiators upstairs stay cold, boiler is running",
            "Boiler runs and pipes are hot at the boiler, radiators stay cold, humming noise", None,
            "asset_boiler_41", trade="heating",
            diagnosis={"cause_id": "circulation_pump_faulty", "confidence": 0.75,
                       "reasoning": "Boiler fires and is hot, but heat doesn't reach the radiators and the pump hums: "
                                    "the circulation pump is likely stuck.",
                       "questions_asked": [{"question": "Is the boiler running?", "answer": "Yes, it's hot"},
                                           {"question": "Do you hear a humming noise?", "answer": "Yes"}]})
        _chat("c_209", c.id, [("in", "Our radiators upstairs stay cold even though the boiler is on"),
                              ("out", "Hi Hannah, do you hear a humming noise from the boiler room?"),
                              ("in", "Yes, a low hum"),
                              ("out", "That sounds like the circulation pump. May I share your details with Heizung Schmidt GmbH?"),
                              ("in", "Yes go ahead")])
        _consent_and_approve(c.id, "c_209", "heizung-schmidt")
        base = now()
        _schedule(c.id, "heizung-schmidt", "tech_tom", [_slot(1, 8, 10, base), _slot(1, 14, 16, base)])
    with _ago(days=5, hours=1):
        invoice = _pdf(["Heizung Schmidt GmbH - Rechnung RE-2026-1142",
                        "Objekt: Lothringerstrasse 41, 52062 Aachen, Whg. 2. OG (Hannah Vogel)",
                        "Anfahrtspauschale (Rahmenvertrag)        1 x 89,00",
                        "Arbeitszeit Heizungstechniker, Std.       2 x 72,00",
                        "Umwaelzpumpe Grundfos ALPHA2 25-60        1 x 186,00",
                        "Netto 419,00   MwSt 19% 79,61   Brutto 498,61 EUR"])
        photo = (DEMO_DIR / "repair_done.jpg").read_bytes() if (DEMO_DIR / "repair_done.jpg").exists() else b""
        extracted = {"invoice_number": "RE-2026-1142", "date": now().date().isoformat(),
                     "net_eur": 419.0, "vat_eur": 79.61, "gross_eur": 498.61,
                     "line_items": [{"desc": "Anfahrtspauschale (Rahmenvertrag)", "qty": 1, "unit_price": 89.0},
                                    {"desc": "Arbeitszeit Heizungstechniker, Std.", "qty": 2, "unit_price": 72.0},
                                    {"desc": "Umwälzpumpe Grundfos ALPHA2 25-60", "qty": 1, "unit_price": 186.0}],
                     "labour_hours": 2.0}
        await services.record_completion(
            c.id, "heizung-schmidt", "Replaced the stuck circulation pump, system bled, all radiators warm",
            ("pump_replaced.jpg", "image/jpeg", photo) if photo else None,
            ("RE-2026-1142.pdf", "application/pdf", invoice), extracted=extracted)
        _chat("c_209", c.id, [("out", "Heizung Schmidt GmbH has finished the repair. Is it warm again?"),
                              ("in", "Yes, all warm again, thank you!")])
        services.tenant_confirms_fixed(c.id, True)
    return c.id


def s6_self_help() -> str:
    """Yusuf, Lothringerstr. 41: hot water tank used up → no technician, saved ~€180."""
    with _ago(days=1, hours=2):
        c = services.open_case(
            "c_208", "repair.hot_water", "normal", "Shower cold in the morning",
            "Flatmates showered just before, water went cold after 5 minutes", None, None,
            diagnosis={"cause_id": "hot_water_used_up", "confidence": 0.9,
                       "reasoning": "Two flatmates showered right before; the radiators are warm and the water "
                                    "was hot earlier, so the storage tank was simply used up.",
                       "questions_asked": [{"question": "Did someone shower just before you?", "answer": "Yes, two people"},
                                           {"question": "Are the radiators warm?", "answer": "Yes"}]})
        _chat("c_208", c.id, [
            ("in", "My shower went cold after 5 minutes this morning 🥶"),
            ("out", "Did someone shower just before you, Yusuf?"),
            ("in", "Yes my two flatmates"),
            ("out", "Then the hot water tank is probably just empty. It reheats in about 30–45 minutes. "
                    "I'll check back in an hour, and if it's still cold I'll send someone."),
        ])
    with _ago(hours=23):
        _chat("c_208", c.id, [("out", "Hi Yusuf, is the hot water back?"), ("in", "Yes all good now, thanks!")])
        services.close_self_help(c.id, "Tank reheated; Yusuf confirmed hot water is back")
    return c.id


def s7_caretaker() -> str:
    """Hannah, Lothringerstr. 41: water pressure low (Viessmann 0A) → caretaker Peter Wolf notified."""
    with _ago(minutes=95):
        c = services.open_case(
            "c_209", "repair.pressure", "normal", "Radiators lukewarm, boiler pressure too low",
            "Display shows 0A, gauge at about 0.6 bar", "0A", "asset_boiler_41", trade="caretaker",
            diagnosis={"cause_id": "low_system_pressure", "confidence": 0.9,
                       "label": "Heating water pressure too low (0A)",  # Viessmann code, not the KB's Vaillant F.22
                       "reasoning": "Display shows 0A and the gauge is at about 0.6 bar: the system pressure is too low. "
                                    "The caretaker can top it up, no technician needed.",
                       "questions_asked": [{"question": "What does the pressure gauge show?", "answer": "About 0.6 bar"}]})
        _chat("c_209", c.id, [
            ("in", "Radiators are only lukewarm and the boiler shows 0A"),
            ("out", "Thanks Hannah. What does the little pressure gauge on the boiler show?"),
            ("in", "Around 0.6"),
            ("out", "That's just low water pressure. I've asked our caretaker Peter Wolf to top it up today, "
                    "no technician needed."),
        ])
        services.notify_caretaker(c.id, "top up system pressure (display 0A, 0.6 bar)")
    return c.id


async def s8_wagner_closed() -> str:
    """Sofia, Lothringerstr. 41: two weeks ago, Wärme Wagner fixed a stuck radiator valve (closed)."""
    with _ago(days=14, hours=5):
        c = services.open_case("c_207", "repair.radiator", "normal", "Bedroom radiator stays cold",
                               "Only the bedroom radiator is cold, the others are fine", None, None,
                               trade="heating")
        _chat("c_207", c.id, [("in", "The radiator in my bedroom doesn't get warm"),
                              ("out", "Hi Sofia! Are the other radiators warm?"),
                              ("in", "Yes, only the bedroom one"),
                              ("out", "Probably a stuck valve. May I share your details with Wärme Wagner KG?"),
                              ("in", "Ok")])
        _consent_and_approve(c.id, "c_207", "waerme-wagner")
        base = now()
        _schedule(c.id, "waerme-wagner", "tech_wagner", [_slot(2, 10, 12, base), _slot(3, 14, 16, base)])
    with _ago(days=12):
        await services.record_completion(c.id, "waerme-wagner",
                                         "Freed the stuck thermostatic valve and bled the radiator", None, None)
        _chat("c_207", c.id, [("out", "Wärme Wagner KG has finished. Is the bedroom radiator warm again?"),
                              ("in", "Yes, toasty 👍")])
        services.tenant_confirms_fixed(c.id, True)
    return c.id


def s9_gruen_requested() -> str:
    """Yusuf, Lothringerstr. 41: living-room thermostat head broken → Heiztechnik Grün, awaiting accept."""
    with _ago(hours=5):
        c = services.open_case("c_208", "repair.radiator", "normal", "Thermostat head on the living-room radiator broken",
                               "The thermostat knob came off and the radiator is stuck on full", None, None,
                               trade="heating")
        _chat("c_208", c.id, [("in", "The thermostat knob on my living room radiator just broke off"),
                              ("out", "Thanks Yusuf, is the radiator stuck hot or cold?"),
                              ("in", "Stuck on full, super hot"),
                              ("out", "Got it. May I share your details with Heiztechnik Grün?"),
                              ("in", "Yes")])
        _consent_and_approve(c.id, "c_208", "heiztechnik-gruen")
    return c.id


def s10_jona_radiator() -> str:
    """Jona, Musterstraße 12 2A (student): bedroom radiator cold at the top → bled it himself, fixed."""
    with _ago(days=24, hours=5):
        c = services.open_case(
            "c_203", "repair.radiator", "normal", "Bedroom radiator only warm at the bottom",
            "Radiator in the bedroom stays cold at the top, gurgling noise", None, None,
            diagnosis={"cause_id": "air_in_radiator", "confidence": 0.85,
                       "label": "Air in the radiator",
                       "reasoning": "Only one radiator, warm at the bottom and cold at the top with a gurgling noise: "
                                    "air trapped in the radiator. Bleeding it fixes this; no technician needed.",
                       "questions_asked": [{"question": "Is it only this radiator?", "answer": "Yes, only the bedroom"},
                                           {"question": "Warm at the bottom and cold at the top?", "answer": "Yes, and it gurgles"}]})
        _chat("c_203", c.id, [
            ("in", "Hi, my bedroom radiator is only warm at the bottom and it gurgles"),
            ("out", "Let's fix it. Is it only this radiator, or are the others cold too?"),
            ("in", "only the bedroom one"),
            ("out", "Then there's air in it. Turn the heating off for the radiator, hold a cup under the small valve at "
                    "the top and open it a quarter turn with a radiator key until water comes out. Tell me if it works."),
        ])
    with _ago(days=24, hours=4):
        _chat("c_203", c.id, [("in", "done, it's warm everywhere now!"), ("out", "Great, glad it's warm again.")])
        services.close_self_help(c.id, "Jona bled the radiator; warm again")
    return c.id


def s11_jona_fuse() -> str:
    """Jona, 2A: no power in the kitchen → tripped fuse (kettle + toaster), reset, fixed."""
    with _ago(days=9, hours=3):
        c = services.open_case(
            "c_203", "repair.electrical", "normal", "No power in the kitchen",
            "Kitchen sockets dead after using the kettle and the toaster together", None, None,
            diagnosis={"cause_id": "tripped_breaker", "confidence": 0.9,
                       "label": "Tripped fuse",
                       "reasoning": "Only the kitchen sockets, right after running the kettle and toaster together: "
                                    "an overloaded circuit tripped its fuse. Switching it back on fixes it.",
                       "questions_asked": [{"question": "Is one switch in the fuse box flipped down?", "answer": "Yes, one"}]})
        _chat("c_203", c.id, [
            ("in", "kitchen has no power, the rest of the flat is fine"),
            ("out", "Let's check. Have a look at the fuse box next to your front door: is one switch flipped down?"),
            ("in", "yes one is down"),
            ("out", "Switch it back up. Kettle and toaster at the same time can overload the circuit, so best use them "
                    "one after the other. Does the kitchen have power again?"),
            ("in", "yes works again, thanks"),
        ])
        services.close_self_help(c.id, "Fuse reset by Jona; kitchen power back")
    return c.id



async def _schmidt_past_job(contact_id: str, asset_id: str | None, title: str, symptoms: str, cause_id: str,
                            reasoning: str, chat: list[tuple[str, str]], days: int, tech_id: str,
                            invoice_no: str, lines: list[tuple[str, int, float]], report: str) -> str:
    """A finished Heizung Schmidt job: consent → approval → slot → completion with invoice → tenant confirms."""
    with _ago(days=days, hours=4):
        c = services.open_case(contact_id, "repair.heating", "urgent", title, symptoms, None, asset_id,
                               trade="heating",
                               diagnosis={"cause_id": cause_id, "confidence": 0.8, "reasoning": reasoning,
                                          "questions_asked": []})
        _chat(contact_id, c.id, chat)
        _consent_and_approve(c.id, contact_id, "heizung-schmidt")
        base = now()
        _schedule(c.id, "heizung-schmidt", tech_id, [_slot(1, 8, 10, base), _slot(1, 10, 12, base)])
    with _ago(days=days - 1, hours=2):
        net = round(sum(q * p for _, q, p in lines), 2)
        vat = round(net * 0.19, 2)
        gross = round(net + vat, 2)
        pdf = _pdf([f"Heizung Schmidt GmbH - Rechnung {invoice_no}"]
                   + [f"{d}   {q} x {p:.2f}" for d, q, p in lines]
                   + [f"Netto {net:.2f}   MwSt 19% {vat:.2f}   Brutto {gross:.2f} EUR"])
        extracted = {"invoice_number": invoice_no, "date": now().date().isoformat(), "net_eur": net,
                     "vat_eur": vat, "gross_eur": gross,
                     "line_items": [{"desc": d, "qty": q, "unit_price": p} for d, q, p in lines]}
        await services.record_completion(c.id, "heizung-schmidt", report, None,
                                         (f"{invoice_no}.pdf", "application/pdf", pdf), extracted=extracted)
        _chat(contact_id, c.id, [("out", "Heizung Schmidt GmbH has finished the repair. Is everything working again?"),
                                 ("in", "Yes, all good, thanks!")])
        services.tenant_confirms_fixed(c.id, True)
    return c.id


async def s12_schmidt_ignition() -> str:
    """Aylin, Musterstr. 12 1A, five weeks ago: boiler F.28, ignition electrode replaced."""
    return await _schmidt_past_job(
        "c_204", "asset_boiler_1", "No heating and no hot water, boiler shows F.28",
        "Boiler display F.28, radiators and taps cold", "boiler_fault",
        "F.28 means the ignition failed; with heating and hot water both off it's the boiler.",
        [("in", "Heating and hot water are off, the boiler says F.28"),
         ("out", "That means the boiler's ignition failed (error code F.28). That needs a heating technician. "
                 "May I share your details with Heizung Schmidt GmbH?"), ("in", "Yes please")],
        34, "tech_tom", "RE-2026-1061",
        [("Anfahrtspauschale (Rahmenvertrag)", 1, 89.0), ("Arbeitszeit Heizungstechniker, Std.", 1, 72.0),
         ("Zuendelektrode Vaillant ecoTEC", 1, 38.5)],
        "Replaced the ignition electrode, boiler fires reliably, F.28 cleared")


async def s13_schmidt_valve() -> str:
    """Mateusz, Musterstr. 12 3B, three weeks ago: radiator valve stuck, replaced."""
    return await _schmidt_past_job(
        "c_205", None, "Living-room radiator stays cold, valve stuck",
        "Thermostat turns but the radiator stays cold, other rooms warm", "radiator_valve_stuck",
        "Only one radiator, the others are warm and bleeding didn't help: the valve pin is stuck.",
        [("in", "My living room radiator is cold, the others are fine"),
         ("out", "Did bleeding the radiator help?"), ("in", "No, still cold"),
         ("out", "Then the valve is probably stuck. May I share your details with Heizung Schmidt GmbH?"),
         ("in", "Sure")],
        19, "tech_tom", "RE-2026-1098",
        [("Anfahrtspauschale (Rahmenvertrag)", 1, 89.0), ("Arbeitszeit Heizungstechniker, Std.", 1, 72.0),
         ("Thermostatventil-Unterteil Heimeier", 1, 24.9)],
        "Replaced the stuck thermostatic valve insert, radiator heats evenly")


async def s14_schmidt_service() -> str:
    """Grace, Musterstr. 12 3C, twelve days ago: boiler losing pressure, expansion vessel recharged."""
    return await _schmidt_past_job(
        "c_206", "asset_boiler_1", "Boiler keeps losing pressure",
        "Pressure drops below 1 bar every few days, refilled twice", "low_system_pressure",
        "Pressure keeps dropping after refills: a recurring loss points to the expansion vessel, a technician job.",
        [("in", "The boiler pressure keeps dropping, the caretaker refilled it twice"),
         ("out", "If it keeps dropping after refills, a technician should check the expansion vessel. "
                 "May I share your details with Heizung Schmidt GmbH?"), ("in", "Yes")],
        12, "tech_ali", "RE-2026-1123",
        [("Anfahrtspauschale (Rahmenvertrag)", 1, 89.0), ("Arbeitszeit Heizungstechniker, Std.", 1.5, 72.0),
         ("Ausdehnungsgefaess Vordruck angepasst", 1, 0.0)],
        "Recharged the expansion vessel to 1.0 bar, system pressure stable at 1.6 bar")


SCENARIOS = [s12_schmidt_ignition, s10_jona_radiator, s13_schmidt_valve, s8_wagner_closed, s14_schmidt_service, s11_jona_fuse, s5_closed_invoiced, s4_scheduled_electrical, s6_self_help,
             s3_awaiting_technician, s9_gruen_requested, s2_requested, s7_caretaker, s1_approval_pending]


async def load() -> list[dict]:
    """Create all demo scenarios (call right after a reset). Oldest first, so case ids follow time."""
    import inspect
    out = []
    for fn in SCENARIOS:
        res = fn()
        cid = await res if inspect.isawaitable(res) else res
        case = services.get_case(cid)
        out.append({"scenario": fn.__name__, "case_id": cid, "status": case.status,
                    "unit_id": case.unit_id, "partner_id": case.partner_id})
    return out

