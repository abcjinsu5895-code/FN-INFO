# ============================================================
#  주요 지표 가져오기
#   - 기준금리: 한국, 미국
#   - 시장 지표: 금리 / 환율 / 주식 / 원자재·심리 (+ 5일·3개월 추이)
# ============================================================

import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# ------------------------------------------------------------
# [설정]
# ------------------------------------------------------------

# 한국 기준금리 예비값: 한국은행 API 키가 없거나 실패하면 이 값을 보여줘요.
# 금통위에서 금리가 바뀌면 여기 숫자만 고치면 돼요. (2026-08-27 인상 기준)
KOREA_RATE_FALLBACK = 3.00

# 미국 기준금리 예비값 (하단, 상단): 온라인에서 못 가져올 때만 써요. (2026-09-16 인상 기준)
US_RATE_FALLBACK = (3.75, 4.00)

# 야후 파이낸스에서 가져올 시세, 묶음별로 정리
#   "표시 이름": (종목코드, 단위, 소수점)
#   단위가 "%"면 금리로 보고 변화를 bp(0.01%p)로 보여줘요.
GROUPS = {
    "금리": {
        "미국 10년물": ("^TNX", "%", 2),
        # 미국 2년물은 야후에 믿을 만한 데이터가 없어서 미국 재무부 공식 데이터로 따로 가져와요.
    },
    "환율": {
        "원/달러": ("KRW=X", "원", 1),
        "달러인덱스": ("DX-Y.NYB", "", 2),
        "엔/달러": ("JPY=X", "엔", 2),
        "위안/달러": ("CNY=X", "위안", 4),
    },
    "주식": {
        "코스피": ("^KS11", "", 2),
        "S&P 500": ("^GSPC", "", 2),
        "나스닥": ("^IXIC", "", 2),
        "닛케이": ("^N225", "", 2),
        "상해종합": ("000001.SS", "", 2),
    },
    "원자재·심리": {
        "WTI 유가": ("CL=F", "달러", 2),
        "금": ("GC=F", "달러", 1),
        "구리": ("HG=F", "달러", 3),
        "VIX 공포지수": ("^VIX", "", 2),
    },
}

# ------------------------------------------------------------


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read().decode("utf-8")


def _yahoo(symbol, period, interval):
    """야후 차트 데이터. 한 번 실패하면 다른 주소로 한 번 더 시도해요."""
    path = f"/v8/finance/chart/{urllib.parse.quote(symbol)}?range={period}&interval={interval}"
    last_error = None
    for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        try:
            time.sleep(0.3)  # 너무 빨리 연달아 요청하지 않게
            return json.loads(_get(host + path))["chart"]["result"][0]
        except Exception as e:
            last_error = e
    raise last_error


def korea_rate():
    """한국은행 기준금리 (한국은행 ECOS API, 키가 있을 때만)"""
    key = os.environ.get("BOK_API_KEY", "").strip()
    if key:
        try:
            end = datetime.now(KST)
            start = end - timedelta(days=180)
            url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/20/"
                   f"722Y001/M/{start:%Y%m}/{end:%Y%m}/0101000")
            rows = json.loads(_get(url))["StatisticSearch"]["row"]
            value = float(rows[-1]["DATA_VALUE"])
            return {"name": "한국 기준금리", "value": f"{value:.2f}%"}
        except Exception as e:
            print(f"[한국 기준금리] API 실패, 예비값 사용: {e}")
    return {"name": "한국 기준금리", "value": f"{KOREA_RATE_FALLBACK:.2f}%"}


def us_rate():
    """미국 기준금리 범위: 뉴욕 연준 → FRED → 예비값 순서로 시도해요."""
    def fmt(low, high):
        return {"name": "미국 기준금리", "value": f"{low:.2f}~{high:.2f}%"}

    try:  # 1) 뉴욕 연준 공식 API
        data = json.loads(_get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json"))
        r = data["refRates"][0]
        return fmt(float(r["targetRateFrom"]), float(r["targetRateTo"]))
    except Exception as e:
        print(f"[미국 기준금리] 뉴욕 연준 실패: {e}")

    def last_value(series):  # 2) 세인트루이스 연준 FRED
        text = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
        rows = list(csv.reader(io.StringIO(text)))[1:]
        values = [r[-1] for r in rows if r and r[-1] not in (".", "")]
        return float(values[-1])
    try:
        return fmt(last_value("DFEDTARL"), last_value("DFEDTARU"))
    except Exception as e:
        print(f"[미국 기준금리] FRED 실패: {e}")

    return fmt(*US_RATE_FALLBACK)  # 3) 예비값


def format_value(price, unit, digits):
    if unit == "bp":
        return f"{price:+.0f}bp"
    if unit == "%":
        return f"{price:,.{digits}f}%"
    return f"{price:,.{digits}f} {unit}".strip()


def format_change(diff, base, unit, digits):
    """변화량을 보기 좋게: 금리는 bp, 나머지는 값과 % 같이"""
    if unit == "%":
        return f"{diff * 100:+.0f}bp"
    if unit == "bp":
        return f"{diff:+.0f}bp"
    pct = f" ({diff / base * 100:+.2f}%)" if base else ""
    return f"{diff:+,.{digits}f}{pct}"


def _series(res, time_fmt):
    """야후 응답에서 (시점, 값) 목록을 뽑아요."""
    stamps = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0]["close"]
    times, values, raw = [], [], []
    for ts, v in zip(stamps, closes):
        if v is None:
            continue
        times.append(datetime.fromtimestamp(ts, KST).strftime(time_fmt))
        values.append(round(v, 4))
        raw.append(ts)
    return times, values, raw


def quote(name, symbol, unit, digits):
    """현재 시세, 전일 대비 변화, 5일·3개월 추이(시점 포함)"""
    item = {"name": name, "unit": unit, "digits": digits,
            "price": None, "value": "-", "change": None, "trends": {}}

    # 3개월 일별: 현재가와 전일 종가도 여기서 같이 구해요
    try:
        res = _yahoo(symbol, "3mo", "1d")
        meta = res["meta"]
        price = meta["regularMarketPrice"]
        times, values, raw = _series(res, "%Y/%m/%d")
        prev = None
        if values:
            # 마지막 막대가 오늘 거래일이면 그 전날이 '전일 종가'
            off = meta.get("gmtoffset", 0)
            last_day = datetime.fromtimestamp(raw[-1] + off, timezone.utc).date()
            now_day = datetime.fromtimestamp(meta.get("regularMarketTime", raw[-1]) + off, timezone.utc).date()
            if last_day == now_day:
                prev = values[-2] if len(values) >= 2 else None
                values[-1] = round(price, 4)
            else:
                prev = values[-1]
        item["price"] = price
        item["value"] = format_value(price, unit, digits)
        if prev:
            item["change"] = format_change(price - prev, prev, unit, digits)
        if len(values) >= 2:
            item["trends"]["3mo"] = {"times": times, "values": values,
                                     "change": format_change(values[-1] - values[0], values[0], unit, digits)}
    except Exception as e:
        print(f"[{name}] 시세 실패: {e}")
        return item

    # 5일 시간별
    try:
        times, values, _ = _series(_yahoo(symbol, "5d", "60m"), "%m/%d %H:%M")
        if len(values) >= 2:
            item["trends"]["5d"] = {"times": times, "values": values,
                                    "change": format_change(values[-1] - values[0], values[0], unit, digits)}
    except Exception as e:
        print(f"[{name}] 5일 추이 실패: {e}")
    return item


TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")


def treasury_curve(days=66):
    """미국 재무부 공식 국채 금리 (2년물, 10년물 일별 종가). 키 필요 없음."""
    rows = []
    this_year = datetime.now(KST).year
    for year in (this_year, this_year - 1):
        try:
            text = _get(TREASURY_URL.format(year=year))
            for r in csv.DictReader(io.StringIO(text)):
                try:
                    d = datetime.strptime(r["Date"], "%m/%d/%Y")
                    rows.append((d, float(r["2 Yr"]), float(r["10 Yr"])))
                except (KeyError, ValueError):
                    continue
        except Exception as e:
            print(f"[재무부 금리] {year}년 실패: {e}")
        if len(rows) >= days:
            break
    rows = sorted(set(rows))[-days:]
    if len(rows) < 2:
        return None
    return {
        "times": [d.strftime("%Y/%m/%d") for d, _, _ in rows],
        "y2": [y2 for _, y2, _ in rows],
        "y10": [y10 for _, _, y10 in rows],
        "last_date": rows[-1][0].strftime("%m/%d"),
    }


def _daily_item(name, times, values, unit, digits, note):
    """일별 데이터만 있는 지표 칸 (5일 그래프는 최근 6거래일 일별)"""
    item = {"name": name, "unit": unit, "digits": digits, "price": values[-1],
            "value": format_value(values[-1], unit, digits), "note": note, "trends": {}}
    item["change"] = format_change(values[-1] - values[-2], values[-2], unit, digits)
    short = [t[5:] for t in times[-6:]]  # MM/DD
    item["trends"]["5d"] = {"times": short, "values": values[-6:],
                            "change": format_change(values[-1] - values[-6], values[-6], unit, digits)}
    item["trends"]["3mo"] = {"times": times, "values": values,
                             "change": format_change(values[-1] - values[0], values[0], unit, digits)}
    return item


def treasury_items(curve):
    """2년물 칸과 장단기 금리차 칸 (둘 다 재무부 같은 날 종가 기준)"""
    if not curve:
        return []
    note = f"{curve['last_date']} 종가, 미 재무부"
    two = _daily_item("미국 2년물", curve["times"], curve["y2"], "%", 2, note)
    spread_bp = [round((a - b) * 100, 1) for a, b in zip(curve["y10"], curve["y2"])]
    state = "역전" if spread_bp[-1] < 0 else "정상"
    spread = _daily_item("장단기 금리차", curve["times"], spread_bp, "bp", 0,
                         f"10년−2년, {state}, {curve['last_date']} 종가")
    return [two, spread]


def get_all():
    """기준금리와 묶음별 시장 지표를 돌려줘요."""
    rates = [korea_rate(), us_rate()]
    curve = treasury_curve()
    groups = []
    for group_name, quotes in GROUPS.items():
        items = [quote(name, *info) for name, info in quotes.items()]
        if group_name == "금리":
            items += treasury_items(curve)
        groups.append({"name": group_name, "items": items})

    for it in rates:
        print(f"[지표] {it['name']}: {it['value']}")
    for g in groups:
        for it in g["items"]:
            print(f"[지표] {it['name']}: {it['value']} {it.get('change') or ''}")
    return {"rates": rates, "groups": groups, "curve": curve}
