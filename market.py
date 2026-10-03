# ============================================================
#  주요 지표 가져오기: 한국/미국 기준금리, 미국 10년물, 환율, 유가
#  + 시장 지표는 추이(5일 시간별 / 3개월 일별)까지 가져와요
# ============================================================

import csv
import io
import json
import os
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

# 야후 파이낸스에서 가져올 시세 (표시 이름: (종목코드, 단위, 소수점))
QUOTES = {
    "미국 10년물": ("^TNX", "%", 2),
    "원/달러": ("KRW=X", "원", 1),
    "WTI 유가": ("CL=F", "달러", 2),
}

# 추이 기간 (이름: (야후 기간, 간격))
TREND_RANGES = {
    "5d": ("5d", "60m"),    # 최근 5일, 1시간 간격
    "3mo": ("3mo", "1d"),   # 최근 3개월, 하루 간격
}

# ------------------------------------------------------------


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read().decode("utf-8")


def _yahoo(symbol, period, interval):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?range={period}&interval={interval}")
    return json.loads(_get(url))["chart"]["result"][0]


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
    """미국 기준금리 범위 (미국 세인트루이스 연준 FRED, 키 필요 없음)"""
    def last_value(series):
        text = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
        rows = list(csv.reader(io.StringIO(text)))[1:]
        values = [r[-1] for r in rows if r and r[-1] not in (".", "")]
        return float(values[-1])
    try:
        low, high = last_value("DFEDTARL"), last_value("DFEDTARU")
        return {"name": "미국 기준금리", "value": f"{low:.2f}~{high:.2f}%"}
    except Exception as e:
        print(f"[미국 기준금리] 실패: {e}")
        return {"name": "미국 기준금리", "value": "-"}


def format_change(diff, base, unit, digits):
    """변화량을 보기 좋게: 금리는 bp, 나머지는 값과 % 같이"""
    if unit == "%":
        return f"{diff * 100:+.0f}bp"
    pct = f" ({diff / base * 100:+.1f}%)" if base else ""
    return f"{diff:+,.{digits}f}{pct}"


def quote(name, symbol, unit, digits):
    """현재 시세, 전일 대비 변화, 기간별 추이"""
    item = {"name": name, "value": "-", "change": None, "trends": {}}
    try:
        meta = _yahoo(symbol, "1d", "1d")["meta"]
        price = meta["regularMarketPrice"]
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        item["value"] = f"{price:,.{digits}f}%" if unit == "%" else f"{price:,.{digits}f} {unit}"
        if prev:
            item["change"] = format_change(price - prev, prev, unit, digits)
    except Exception as e:
        print(f"[{name}] 현재가 실패: {e}")
        return item

    for key, (period, interval) in TREND_RANGES.items():
        try:
            closes = _yahoo(symbol, period, interval)["indicators"]["quote"][0]["close"]
            values = [v for v in closes if v is not None]
            if len(values) >= 2:
                item["trends"][key] = {
                    "values": values,
                    "change": format_change(values[-1] - values[0], values[0], unit, digits),
                }
        except Exception as e:
            print(f"[{name}] {key} 추이 실패: {e}")
    return item


def get_all():
    """기준금리 2개, 시장 지표 여러 개를 돌려줘요."""
    rates = [korea_rate(), us_rate()]
    quotes = [quote(name, *info) for name, info in QUOTES.items()]
    for it in rates + quotes:
        print(f"[지표] {it['name']}: {it['value']} {it.get('change') or ''}")
    return {"rates": rates, "quotes": quotes}
