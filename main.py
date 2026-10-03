# ============================================================
#  내 거시경제 페이지 만들기
#   - 지표(환율, 유가, 미국채 등): 실행할 때마다(3시간마다) 새로
#   - 기사(국내 3 + 해외 3): 하루 한 번, 아침 8시 이후 첫 실행 때
#  (추가 설치 필요 없음)
# ============================================================

import html
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import market  # 지표 가져오는 부분 (market.py)

# ------------------------------------------------------------
# [설정] 여기만 바꾸면 관심사를 바꿀 수 있어요
# ------------------------------------------------------------

NEWS_HOUR = 8  # 기사는 매일 이 시각(한국 시간) 이후 첫 실행 때 새로 골라요

# 국내: 한국어 구글 뉴스
KOREA = {
    "edition": "hl=ko&gl=KR&ceid=KR:ko",
    "how_many": 3,
    # 주제 이름: 검색어
    "topics": {
        "금리": "기준금리 OR 금리인하 OR 금리인상",
        "물가": "소비자물가 OR 인플레이션",
        "환율": "원달러 환율 OR 환율",
        "성장": "경제성장률 OR GDP OR 경기침체",
        "연준": "연준 OR 파월 OR FOMC",
        "고용": "고용지표 OR 실업률",
        "무역": "수출 OR 무역수지 OR 경상수지",
    },
    # 제목에 있으면 점수를 주는 단어 (음수면 감점)
    "keywords": {
        "기준금리": 5, "한국은행": 4, "한은": 4, "연준": 4, "FOMC": 5,
        "금리": 3, "물가": 3, "인플레": 3, "CPI": 4,
        "환율": 3, "달러": 2, "GDP": 4, "성장률": 4, "경기": 2,
        "침체": 3, "고용": 3, "실업률": 4, "국채": 3, "경상수지": 3,
        "무역수지": 3, "수출": 2, "전망": 1,
        "[포토]": -10, "포토": -3, "부고": -10, "인사": -5, "특징주": -5,
    },
}

# 해외: 영어(미국판) 구글 뉴스
WORLD = {
    "edition": "hl=en-US&gl=US&ceid=US:en",
    "how_many": 3,
    "topics": {
        "금리": "Federal Reserve OR FOMC OR interest rates",
        "물가": "inflation OR CPI",
        "성장": "GDP OR recession OR economic growth",
        "고용": "jobs report OR unemployment OR payrolls",
        "환율": "dollar OR yen OR yuan currency",
        "무역": "tariffs OR trade deficit",
        "중앙은행": "ECB OR Bank of Japan OR PBOC",
    },
    "keywords": {
        "Federal Reserve": 5, "FOMC": 5, "Fed": 4, "Powell": 3,
        "rate cut": 4, "rate hike": 4, "interest rate": 3,
        "inflation": 3, "CPI": 4, "GDP": 4, "recession": 3,
        "payrolls": 4, "unemployment": 3, "jobs": 2,
        "Treasury": 3, "yields": 3, "dollar": 2,
        "ECB": 4, "Bank of Japan": 4, "BOJ": 4, "PBOC": 4,
        "tariff": 3, "economy": 1,
        "podcast": -5, "video": -3, "stocks to buy": -10, "stock to buy": -10,
    },
}

MAX_PER_TOPIC = 1  # 한 주제에서 최대 몇 개까지 (다양하게 보려고 1개)

# ------------------------------------------------------------
# 아래부터는 동작 부분 (안 건드려도 돼요)
# ------------------------------------------------------------

KST = timezone(timedelta(hours=9))
NEWS_FILE = "news.json"  # 고른 기사를 저장해 두는 파일


# ---------- 기사 ----------

def fetch_topic(topic, query, edition):
    """구글 뉴스에서 최근 하루치 기사 목록을 가져와요."""
    q = urllib.parse.quote(f"{query} when:1d")
    url = f"https://news.google.com/rss/search?q={q}&{edition}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            root = ET.fromstring(res.read())
    except Exception as e:
        print(f"[{topic}] 가져오기 실패: {e}")
        return []

    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):  # 제목 끝 " - 언론사" 떼기
            title = title[: -len(" - " + source)]
        try:
            published = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception:
            published = None
        items.append({
            "topic": topic,
            "title": title,
            "link": (it.findtext("link") or "").strip(),
            "source": source,
            "published": published,
        })
    print(f"[{topic}] {len(items)}개 가져옴")
    return items


def score(article, keywords):
    """제목을 보고 점수를 매겨요."""
    s = 0
    title = article["title"].lower()
    for word, point in keywords.items():
        if word.lower() in title:
            s += point
    if article["published"]:  # 최근 기사일수록 약간 가산점
        hours_ago = (datetime.now(KST) - article["published"]).total_seconds() / 3600
        s += max(0, 3 - hours_ago / 8)
    return s


def collect(region):
    """한 지역(국내/해외)의 기사를 모아서 정해진 개수만큼 골라요."""
    articles = []
    for topic, query in region["topics"].items():
        articles += fetch_topic(topic, query, region["edition"])

    for a in articles:
        a["score"] = score(a, region["keywords"])
    articles.sort(key=lambda a: a["score"], reverse=True)

    chosen, seen, topic_count = [], set(), {}
    for a in articles:
        key = a["title"].replace(" ", "").lower()[:18]  # 앞부분 같으면 같은 기사
        if key in seen or a["score"] < 0:
            continue
        if topic_count.get(a["topic"], 0) >= MAX_PER_TOPIC:
            continue
        seen.add(key)
        topic_count[a["topic"]] = topic_count.get(a["topic"], 0) + 1
        chosen.append({
            "topic": a["topic"], "title": a["title"], "link": a["link"],
            "source": a["source"],
            "time": a["published"].strftime("%H:%M") if a["published"] else "",
        })
        if len(chosen) == region["how_many"]:
            break
    return chosen


def load_news():
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def get_news(now):
    """오늘 기사가 이미 있으면 그대로, 없으면(8시 이후) 새로 골라요."""
    saved = load_news()
    today = now.strftime("%Y-%m-%d")
    if saved and (saved["date"] == today or now.hour < NEWS_HOUR):
        print("[기사] 저장된 기사 사용")
        return saved
    print("[기사] 새로 고르는 중")
    news = {
        "date": today,
        "updated": now.strftime("%m월 %d일 %H:%M"),
        "korea": collect(KOREA),
        "world": collect(WORLD),
    }
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=1)
    return news


# ---------- 웹페이지 조각 만들기 ----------

def make_rows(chosen):
    if not chosen:
        return '\n      <li class="empty">기사를 가져오지 못했어요. 다음 실행 때 다시 시도해요.</li>'
    rows = []
    for a in chosen:
        rows.append(f"""
      <li>
        <span class="tag">{html.escape(a['topic'])}</span>
        <a href="{html.escape(a['link'])}" target="_blank" rel="noopener">{html.escape(a['title'])}</a>
        <span class="meta">{html.escape(a['source'])} {a['time']}</span>
      </li>""")
    return "".join(rows)


def direction(change):
    """'+1.2' 같은 글을 보고 오름/내림/보합을 판단해요."""
    if not change:
        return "flat"
    number = change.split(" ")[0].rstrip("bp").replace(",", "")
    try:
        v = float(number)
    except ValueError:
        return "flat"
    return "up" if v > 0 else "down" if v < 0 else "flat"


def sparkline(values, css_class):
    """숫자 목록으로 작은 선 그래프(SVG)를 그려요."""
    w, h, pad = 300, 64, 4
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = w / (len(values) - 1)
    pts = " ".join(
        f"{i * step:.1f},{pad + (h - 2 * pad) * (1 - (v - lo) / span):.1f}"
        for i, v in enumerate(values)
    )
    return (f'<svg class="spark {css_class}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'aria-hidden="true"><polyline points="{pts}" fill="none" '
            f'stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke" '
            f'stroke-linejoin="round"/></svg>')


def make_rates(data):
    cells = []
    for it in data["rates"]:
        cells.append(f"""
      <div class="cell rate">
        <span class="name">{html.escape(it['name'])}</span>
        <span class="value">{html.escape(it['value'])}</span>
      </div>""")
    return "".join(cells)


def make_quotes(data):
    labels = {"5d": "5일", "3mo": "3개월"}
    cells = []
    for it in data["quotes"]:
        change = ""
        if it["change"]:
            change = f'<span class="chg {direction(it["change"])}">전일 대비 {html.escape(it["change"])}</span>'
        charts = ""
        for key, tr in it["trends"].items():
            d = direction(tr["change"])
            charts += f"""
        <div class="trend r-{key}">
          {sparkline(tr['values'], d)}
          <span class="chg {d}">{labels.get(key, key)} {html.escape(tr['change'])}</span>
        </div>"""
        cells.append(f"""
      <div class="cell quote">
        <span class="name">{html.escape(it['name'])}</span>
        <span class="value">{html.escape(it['value'])}</span>
        {change}{charts}
      </div>""")
    return "".join(cells)


def make_page(news, indicators, now):
    with open("template.html", encoding="utf-8") as f:
        template = f.read()
    date_text = f"{now.month}월 {now.day}일 {'월화수목금토일'[now.weekday()]}요일"
    page = (template
            .replace("{{DATE}}", date_text)
            .replace("{{MARKET_TIME}}", now.strftime("%H:%M"))
            .replace("{{NEWS_TIME}}", news["updated"])
            .replace("{{RATES}}", make_rates(indicators))
            .replace("{{QUOTES}}", make_quotes(indicators))
            .replace("{{KOREA}}", make_rows(news["korea"]))
            .replace("{{WORLD}}", make_rows(news["world"])))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("index.html 완성")


if __name__ == "__main__":
    now = datetime.now(KST)
    make_page(get_news(now), market.get_all(), now)
