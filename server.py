"""Lean Swiss Ephemeris MCP server (remote, stateless, free-tier friendly).

Design goals: few tools, short descriptions, compact text output -> low token use.
"""
import os
from datetime import datetime, timedelta
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
ASPECTS = [("conj", 0, 1.0), ("opp", 180, 1.0), ("tri", 120, 1.0), ("squ", 90, 1.0), ("sex", 60, 0.6)]
FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED


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


def positions(jd):
    out = {}
    for name, b in BODIES:
        try:
            r, _ = swe.calc_ut(jd, b, FLAGS)
        except swe.Error:
            continue
        out[name] = (r[0], r[3] < 0)
    if "Node" in out:
        out["SNode"] = ((out["Node"][0] + 180) % 360, False)
    return out


def houses(jd, lat, lon, hsys):
    try:
        cusps, asc = swe.houses_ex(jd, lat, lon, hsys.encode())
    except swe.Error:
        cusps, asc = swe.houses_ex(jd, lat, lon, b"W")
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


def chart_block(jd, lat, lon, hsys, known_time=True):
    P = positions(jd)
    lines = []
    cusps = None
    if known_time:
        cusps, asc, mc = houses(jd, lat, lon, hsys)
        lines.append(f"ASC {fmt(asc)} MC {fmt(mc)}")
        lines.append("H " + " ".join(f"{i+1}:{fmt(c)}" for i, c in enumerate(cusps)))
    row = []
    for n, (l, rx) in P.items():
        h = f" h{house_of(l, cusps)}" if cusps else ""
        row.append(f"{n} {fmt(l)}{'R' if rx else ''}{h}")
    lines.append("; ".join(row))
    return P, cusps, lines


def parse_time(time):
    return (time or "").lower() not in ("", "unknown", "?")


@mcp.tool()
def natal(date: str, time: str, tz: str, lat: float, lon: float, hsys: str = "P", orb: float = 8) -> str:
    """Natal chart. date YYYY-MM-DD, time HH:MM local ('unknown' = no houses), tz IANA e.g. Asia/Hong_Kong, lat/lon decimal (E+, N+), hsys P/W/K/R/E."""
    known = parse_time(time)
    jd = to_jd(date, time if known else "12:00", tz)
    P, _, lines = chart_block(jd, lat, lon, hsys, known)
    lines.append("Asp: " + "; ".join(aspects(P, P, orb, same=True)))
    return "\n".join(lines)


@mcp.tool()
def transits(date: str, time: str, tz: str, lat: float, lon: float, on: str, hsys: str = "P", orb: float = 2, moon: bool = False) -> str:
    """Transit planets on date `on` (YYYY-MM-DD, noon UT) vs natal chart. Same natal args as natal()."""
    known = parse_time(time)
    N = positions(to_jd(date, time if known else "12:00", tz))
    jd_t = to_jd(on, "12:00", "UTC")
    T = positions(jd_t)
    skip = {"SNode", "Lil", "Chi"} | (set() if moon else {"Moon"})
    T = {k: v for k, v in T.items() if k not in skip}
    cusps = houses(to_jd(date, time, tz), lat, lon, hsys)[0] if known else None
    head = "T: " + "; ".join(f"{n} {fmt(l)}{'R' if rx else ''}" + (f" h{house_of(l, cusps)}" if cusps else "") for n, (l, rx) in T.items())
    return head + "\nAsp(T→N): " + "; ".join(aspects(T, N, orb))


@mcp.tool()
def progressed(date: str, time: str, tz: str, lat: float, lon: float, on: str, hsys: str = "P", orb: float = 1) -> str:
    """Secondary progressions (day-for-a-year) to date `on` (YYYY-MM-DD): progressed positions + aspects to natal."""
    known = parse_time(time)
    t = time if known else "12:00"
    jd_n = to_jd(date, t, tz)
    jd_p = jd_n + (to_jd(on, "12:00", "UTC") - jd_n) / 365.24219
    N = positions(jd_n)
    P, cusps, lines = chart_block(jd_p, lat, lon, hsys, known)
    if known:
        ncusps = houses(jd_n, lat, lon, hsys)[0]
        lines = lines[:1] + ["P: " + "; ".join(
            f"{n} {fmt(l)}{'R' if rx else ''} h{house_of(l, ncusps)}" for n, (l, rx) in P.items())]
    else:
        lines = ["P: " + "; ".join(f"{n} {fmt(l)}{'R' if rx else ''}" for n, (l, rx) in P.items())]
    P2 = {k: v for k, v in P.items() if k not in ("SNode", "Lil")}
    lines.append("Asp(P→N): " + "; ".join(aspects(P2, N, orb)))
    return "\n".join(lines)


@mcp.tool()
def synastry(date1: str, time1: str, tz1: str, lat1: float, lon1: float,
             date2: str, time2: str, tz2: str, lat2: float, lon2: float,
             hsys: str = "P", orb: float = 5) -> str:
    """Synastry: person 2 planets over person 1 houses + inter-aspects (P1→P2). Args as natal() with suffixes 1/2."""
    k1, k2 = parse_time(time1), parse_time(time2)
    jd1 = to_jd(date1, time1 if k1 else "12:00", tz1)
    jd2 = to_jd(date2, time2 if k2 else "12:00", tz2)
    A, B = positions(jd1), positions(jd2)
    out = []
    if k1:
        c1 = houses(jd1, lat1, lon1, hsys)[0]
        out.append("P2 in P1 houses: " + "; ".join(f"{n} h{house_of(l, c1)}" for n, (l, _) in B.items()))
    if k2:
        c2 = houses(jd2, lat2, lon2, hsys)[0]
        out.append("P1 in P2 houses: " + "; ".join(f"{n} h{house_of(l, c2)}" for n, (l, _) in A.items()))
    out.append("Asp: " + "; ".join(aspects(A, B, orb)))
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
