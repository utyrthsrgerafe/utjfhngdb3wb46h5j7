"""Lean Swiss Ephemeris MCP server (remote, stateless, free-tier friendly).

Design goals: few tools, short descriptions, compact text output -> low token use.
"""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import swisseph as swe
from mcp.server.fastmcp import FastMCP

HERE = os.path.dirname(os.path.abspath(__file__))
swe.set_ephe_path(os.path.join(HERE, "ephe"))

SECRET = os.environ.get("MCP_SECRET", "").strip("/")
PATH = f"/{SECRET}/mcp" if SECRET else "/mcp"

mcp = FastMCP(
    "swisseph",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "7860")),
    stateless_http=True,
    json_response=True,
    streamable_http_path=PATH,
)

from starlette.requests import Request
from starlette.responses import PlainTextResponse


@mcp.custom_route("/health", methods=["GET", "HEAD"])
async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


SIGNS = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
BODIES = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mer", swe.MERCURY), ("Ven", swe.VENUS),
    ("Mar", swe.MARS), ("Jup", swe.JUPITER), ("Sat", swe.SATURN), ("Ura", swe.URANUS),
    ("Nep", swe.NEPTUNE), ("Plu", swe.PLUTO), ("Chi", swe.CHIRON), ("Node", swe.TRUE_NODE),
    ("Lil", swe.MEAN_APOG),
]
# Heliocentric: Earth replaces Sun/Moon; nodes and apogee are meaningless.
HELIO_BODIES = [
    ("Ear", swe.EARTH), ("Mer", swe.MERCURY), ("Ven", swe.VENUS), ("Mar", swe.MARS),
    ("Jup", swe.JUPITER), ("Sat", swe.SATURN), ("Ura", swe.URANUS), ("Nep", swe.NEPTUNE),
    ("Plu", swe.PLUTO), ("Chi", swe.CHIRON),
]
ASPECTS = [("conj", 0, 1.0), ("opp", 180, 1.0), ("tri", 120, 1.0), ("squ", 90, 1.0), ("sex", 60, 0.6)]
FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED
AYANAMSA = {"lahiri": "LAHIRI", "fagan": "FAGAN_BRADLEY", "kp": "KRISHNAMURTI",
            "krishnamurti": "KRISHNAMURTI", "raman": "RAMAN", "yukteshwar": "YUKTESHWAR",
            "deluce": "DELUCE"}


class Cfg:
    """Parsed `opt` string: 'sid=lahiri', 'topo', 'helio' (comma/space separated)."""

    def __init__(self, opt=""):
        self.fl, self.hfl = FLAGS, 0
        self.sid = self.sid_name = None
        self.topo = self.helio = False
        for tok in re.split(r"[,\s]+", (opt or "").lower().strip()):
            if not tok:
                continue
            if tok == "topo":
                self.topo = True
            elif tok == "helio":
                self.helio = True
            elif tok.startswith("sid"):
                name = tok[3:].lstrip("=:") or "lahiri"
                const = AYANAMSA.get(name, name.upper())
                if not hasattr(swe, "SIDM_" + const):
                    raise ValueError(f"unknown ayanamsa '{name}'; try lahiri, fagan, kp, raman, yukteshwar, deluce")
                self.sid, self.sid_name = getattr(swe, "SIDM_" + const), const
            else:
                raise ValueError(f"unknown opt '{tok}'; use sid=<ayanamsa>, topo, helio")
        if self.helio:
            self.topo = False  # not meaningful together
            self.fl |= swe.FLG_HELCTR
        if self.topo:
            self.fl |= swe.FLG_TOPOCTR
        if self.sid is not None:
            self.fl |= swe.FLG_SIDEREAL
            self.hfl = swe.FLG_SIDEREAL

    def tag(self):
        t = [f"sid={self.sid_name}"] if self.sid is not None else []
        t += ["topo"] if self.topo else []
        t += ["helio"] if self.helio else []
        return f"[{' '.join(t)}]" if t else ""

    def prep(self, lat, lon):
        if self.sid is not None:
            swe.set_sid_mode(self.sid, 0, 0)
        if self.topo:
            swe.set_topo(lon, lat, 0)


def fmt(lon):
    lon %= 360
    s = int(lon // 30)
    d = lon - s * 30
    return f"{int(d):02d}{SIGNS[s]}{int((d % 1) * 60):02d}"


def to_jd(date, time, tz):
    """Local civil time in IANA tz -> Julian day (UT)."""
    h, m = (time.split(":") + ["0"])[:2]
    local = datetime.strptime(date, "%Y-%m-%d").replace(
        hour=int(h), minute=int(m), tzinfo=ZoneInfo(tz))
    u = local.astimezone(ZoneInfo("UTC"))
    return swe.julday(u.year, u.month, u.day, u.hour + u.minute / 60)


def positions(jd, cfg, lat=0.0, lon=0.0):
    cfg.prep(lat, lon)
    out = {}
    for name, b in (HELIO_BODIES if cfg.helio else BODIES):
        try:
            r, _ = swe.calc_ut(jd, b, cfg.fl)
        except swe.Error:
            continue
        out[name] = (r[0], r[3] < 0)
    if "Node" in out:
        out["SNode"] = ((out["Node"][0] + 180) % 360, False)
    return out


def houses(jd, lat, lon, hsys, cfg):
    cfg.prep(lat, lon)
    try:
        cusps, asc = swe.houses_ex(jd, lat, lon, hsys.encode(), cfg.hfl)
    except swe.Error:
        cusps, asc = swe.houses_ex(jd, lat, lon, b"W", cfg.hfl)
    return list(cusps), asc[0], asc[1]


def house_of(lon, cusps):
    for i in range(12):
        a, b = cusps[i], cusps[(i + 1) % 12]
        if (lon - a) % 360 < (b - a) % 360:
            return i + 1
    return 1


def aspects(A, B, orb, same=False, cap=30):
    rows = []
    for na, (la, _) in A.items():
        if na == "SNode":
            continue
        for nb, (lb, _) in B.items():
            if nb == "SNode" or (same and na >= nb):
                continue
            d = abs((la - lb + 180) % 360 - 180)
            for an, ang, k in ASPECTS:
                o = abs(d - ang)
                if o <= orb * k:
                    rows.append((o, f"{na} {an} {nb} {o:.1f}"))
    return [r for _, r in sorted(rows)][:cap]


def parse_time(time):
    return (time or "").lower() not in ("", "unknown", "?")


def prep_time(time, cfg):
    """-> (time string for JD, whether houses/angles can be shown)."""
    ok = parse_time(time)
    return (time if ok else "12:00"), (ok and not cfg.helio)


def chart_block(jd, lat, lon, hsys, show_houses, cfg):
    P = positions(jd, cfg, lat, lon)
    lines, cusps = [], None
    if show_houses:
        cusps, asc, mc = houses(jd, lat, lon, hsys, cfg)
        lines.append(f"ASC {fmt(asc)} MC {fmt(mc)}")
        lines.append("H " + " ".join(f"{i+1}:{fmt(c)}" for i, c in enumerate(cusps)))
    row = []
    for n, (l, rx) in P.items():
        h = f" h{house_of(l, cusps)}" if cusps else ""
        row.append(f"{n} {fmt(l)}{'R' if rx else ''}{h}")
    lines.append("; ".join(row))
    return P, cusps, lines


def head(cfg, lines):
    return ([cfg.tag()] if cfg.tag() else []) + lines


@mcp.tool()
def natal(date: str, time: str, tz: str, lat: float, lon: float, hsys: str = "P", orb: float = 8, opt: str = "") -> str:
    """Natal chart. date YYYY-MM-DD, time HH:MM local ('unknown' = no houses), tz IANA e.g. Asia/Hong_Kong, lat/lon decimal (E+, N+), hsys P/W/K/R/E. opt (optional): 'sid=lahiri|fagan|kp|raman', 'topo', 'helio', comma-separated; default tropical geocentric."""
    cfg = Cfg(opt)
    t, show = prep_time(time, cfg)
    jd = to_jd(date, t, tz)
    P, _, lines = chart_block(jd, lat, lon, hsys, show, cfg)
    lines.append("Asp: " + "; ".join(aspects(P, P, orb, same=True)))
    return "\n".join(head(cfg, lines))


@mcp.tool()
def transits(date: str, time: str, tz: str, lat: float, lon: float, on: str, hsys: str = "P", orb: float = 2, moon: bool = False, opt: str = "") -> str:
    """Transit planets on date `on` (YYYY-MM-DD, noon UT) vs natal chart. Same natal args and opt as natal()."""
    cfg = Cfg(opt)
    t, show = prep_time(time, cfg)
    jd_n = to_jd(date, t, tz)
    N = positions(jd_n, cfg, lat, lon)
    T = positions(to_jd(on, "12:00", "UTC"), cfg, lat, lon)
    skip = {"SNode", "Lil", "Chi"} | (set() if moon else {"Moon"})
    T = {k: v for k, v in T.items() if k not in skip}
    cusps = houses(jd_n, lat, lon, hsys, cfg)[0] if show else None
    line = "T: " + "; ".join(f"{n} {fmt(l)}{'R' if rx else ''}" + (f" h{house_of(l, cusps)}" if cusps else "") for n, (l, rx) in T.items())
    return "\n".join(head(cfg, [line, "Asp(T→N): " + "; ".join(aspects(T, N, orb))]))


@mcp.tool()
def progressed(date: str, time: str, tz: str, lat: float, lon: float, on: str, hsys: str = "P", orb: float = 1, opt: str = "") -> str:
    """Secondary progressions (day-for-a-year) to date `on` (YYYY-MM-DD): progressed positions + aspects to natal. Same natal args and opt as natal()."""
    cfg = Cfg(opt)
    t, show = prep_time(time, cfg)
    jd_n = to_jd(date, t, tz)
    jd_p = jd_n + (to_jd(on, "12:00", "UTC") - jd_n) / 365.24219
    N = positions(jd_n, cfg, lat, lon)
    P, _, lines = chart_block(jd_p, lat, lon, hsys, show, cfg)
    if show:
        ncusps = houses(jd_n, lat, lon, hsys, cfg)[0]
        lines = lines[:1] + ["P: " + "; ".join(
            f"{n} {fmt(l)}{'R' if rx else ''} h{house_of(l, ncusps)}" for n, (l, rx) in P.items())]
    else:
        lines = ["P: " + "; ".join(f"{n} {fmt(l)}{'R' if rx else ''}" for n, (l, rx) in P.items())]
    P2 = {k: v for k, v in P.items() if k not in ("SNode", "Lil")}
    lines.append("Asp(P→N): " + "; ".join(aspects(P2, N, orb)))
    return "\n".join(head(cfg, lines))


@mcp.tool()
def synastry(date1: str, time1: str, tz1: str, lat1: float, lon1: float,
             date2: str, time2: str, tz2: str, lat2: float, lon2: float,
             hsys: str = "P", orb: float = 5, opt: str = "") -> str:
    """Synastry: person 2 planets over person 1 houses + inter-aspects (P1→P2). Args and opt as natal() with suffixes 1/2."""
    cfg = Cfg(opt)
    t1, s1 = prep_time(time1, cfg)
    t2, s2 = prep_time(time2, cfg)
    jd1, jd2 = to_jd(date1, t1, tz1), to_jd(date2, t2, tz2)
    A, B = positions(jd1, cfg, lat1, lon1), positions(jd2, cfg, lat2, lon2)
    out = []
    if s1:
        c1 = houses(jd1, lat1, lon1, hsys, cfg)[0]
        out.append("P2 in P1 houses: " + "; ".join(f"{n} h{house_of(l, c1)}" for n, (l, _) in B.items()))
    if s2:
        c2 = houses(jd2, lat2, lon2, hsys, cfg)[0]
        out.append("P1 in P2 houses: " + "; ".join(f"{n} h{house_of(l, c2)}" for n, (l, _) in A.items()))
    out.append("Asp: " + "; ".join(aspects(A, B, orb)))
    return "\n".join(head(cfg, out))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
