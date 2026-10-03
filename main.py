# ============================================================
#  내 거시경제 페이지 만들기
#   - 지표(환율, 유가, 미국채 등): 실행할 때마다(3시간마다) 새로
#   - 기사(국내 3 + 해외 3) + AI 해설: 하루 한 번, 아침 7시 이후 첫 실행 때
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

import insight  # AI 해설 만드는 부분 (insight.py)
import market   # 지표 가져오는 부분 (market.py)
import signals  # 규칙 기반 신호 해석 (signals.py)

# ------------------------------------------------------------
# [설정] 여기만 바꾸면 관심사를 바꿀 수 있어요
# ------------------------------------------------------------

NEWS_HOUR = 7  # 기사는 매일 이 시각(한국 시간) 이후 첫 실행 때 새로 골라요

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

# 전쟁·지정학: 하루 한 번이 아니라 3시간마다(실행할 때마다) 새로 골라요.
# 분쟁 상황이 바뀌면 topics의 검색어만 고치면 돼요.
WAR_KOREA = {
    "edition": "hl=ko&gl=KR&ceid=KR:ko",
    "how_many": 2,
    "max_per_topic": 2,
    "recency": 3,  # 최신 기사에 가산점을 더 크게
    "topics": {
        "휴전·종전": "휴전 OR 종전 OR 평화협상 OR 정전",
        "중동": "이란 OR 호르무즈 OR 헤즈볼라 OR 이스라엘 공습",
        "우크라이나": "우크라이나 러시아 전쟁",
    },
    "keywords": {
        "휴전": 5, "종전": 5, "정전": 4, "평화": 3, "합의": 3, "협상": 3, "결렬": 4,
        "호르무즈": 4, "봉쇄": 3, "공습": 2, "재개": 2, "미사일": 2,
        "이란": 2, "트럼프": 1, "유가": 2,
        "[포토]": -10, "포토": -3, "부고": -10,
    },
}
WAR_WORLD = {
    "edition": "hl=en-US&gl=US&ceid=US:en",
    "how_many": 2,
    "max_per_topic": 2,
    "recency": 3,
    "topics": {
        "휴전·종전": "ceasefire OR truce OR peace talks OR peace deal",
        "중동": "Iran OR Hormuz OR Hezbollah",
        "우크라이나": "Ukraine Russia war",
    },
    "keywords": {
        "ceasefire": 5, "truce": 5, "peace deal": 5, "peace talks": 4, "agreement": 3,
        "collapse": 4, "talks": 2, "Hormuz": 4, "blockade": 3, "strikes": 2,
        "resume": 2, "missile": 2, "oil": 2,
        "podcast": -5, "video": -3, "live updates": -1,
    },
}

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


def score(article, keywords, recency=1):
    """제목을 보고 점수를 매겨요."""
    s = 0
    title = article["title"].lower()
    for word, point in keywords.items():
        if word.lower() in title:
            s += point
    if article["published"]:  # 최근 기사일수록 약간 가산점
        hours_ago = (datetime.now(KST) - article["published"]).total_seconds() / 3600
        s += recency * max(0, 3 - hours_ago / 8)
    return s


def collect(region):
    """한 지역(국내/해외)의 기사를 모아서 정해진 개수만큼 골라요."""
    articles = []
    for topic, query in region["topics"].items():
        articles += fetch_topic(topic, query, region["edition"])

    for a in articles:
        a["score"] = score(a, region["keywords"], region.get("recency", 1))
    articles.sort(key=lambda a: a["score"], reverse=True)

    chosen, seen, topic_count = [], set(), {}
    for a in articles:
        key = a["title"].replace(" ", "").lower()[:18]  # 앞부분 같으면 같은 기사
        if key in seen or a["score"] < 0:
            continue
        if topic_count.get(a["topic"], 0) >= region.get("max_per_topic", MAX_PER_TOPIC):
            continue
        seen.add(key)
        topic_count[a["topic"]] = topic_count.get(a["topic"], 0) + 1
        chosen.append({
            "topic": a["topic"], "title": a["title"], "link": a["link"],
            "source": a["source"],
            "time": a["published"].strftime("%m/%d %H:%M") if a["published"] else "",
        })
        if len(chosen) == region["how_many"]:
            break
    return chosen


def load_news():
    if os.path.exists(NEWS_FILE):
        with open(NEWS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def get_war():
    """전쟁·지정학 최신 기사 (실행할 때마다 새로)"""
    out, seen = [], set()
    for a in collect(WAR_KOREA) + collect(WAR_WORLD):
        if a["link"] not in seen:
            seen.add(a["link"])
            out.append(a)
    return out


def get_news(now, indicators, found, war):
    """오늘 기사가 이미 있으면 그대로, 없으면(7시 이후) 새로 골라요. 해설도 같이."""
    saved = load_news()
    today = now.strftime("%Y-%m-%d")
    if saved and (saved["date"] == today or now.hour < NEWS_HOUR):
        news = saved
        print("[기사] 저장된 기사 사용")
        if news.get("insight"):
            return news
        # 해설만 빠져 있으면(키를 나중에 넣은 경우 등) 해설만 다시 시도
        if news["date"] != today:
            return news
    else:
        print("[기사] 새로 고르는 중")
        news = {
            "date": today,
            "updated": now.strftime("%m월 %d일 %H:%M"),
            "korea": collect(KOREA),
            "world": collect(WORLD),
        }
    news["insight"] = insight.make_insight(indicators, news, today, found, war)
    news["insight_time"] = now.strftime("%H:%M")
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=1)
    return news


# ---------- 웹페이지 조각 만들기 ----------

def esc(text):
    return html.escape(str(text))


def make_rows(chosen):
    if not chosen:
        return '\n      <li class="empty">기사를 가져오지 못했어요. 다음 실행 때 다시 시도해요.</li>'
    rows = []
    for a in chosen:
        rows.append(f"""
      <li>
        <span class="tag">{esc(a['topic'])}</span>
        <a href="{esc(a['link'])}" target="_blank" rel="noopener">{esc(a['title'])}</a>
        <span class="meta">{esc(a['source'])} {a['time']}</span>
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


def sparkline(trend, css_class, unit, digits):
    """시점 정보가 들어 있는 작은 선 그래프(SVG). 마우스를 올리면 값이 보여요."""
    values = trend["values"]
    w, h, pad = 300, 64, 4
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = w / (len(values) - 1)
    pts = " ".join(
        f"{i * step:.1f},{pad + (h - 2 * pad) * (1 - (v - lo) / span):.1f}"
        for i, v in enumerate(values)
    )
    data_t = esc(json.dumps(trend["times"], ensure_ascii=False))
    data_v = esc(json.dumps(values))
    return (f'<div class="plot"><svg class="spark {css_class}" viewBox="0 0 {w} {h}" '
            f'preserveAspectRatio="none" data-t="{data_t}" data-v="{data_v}" '
            f'data-unit="{esc(unit)}" data-d="{digits}">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="2" '
            f'vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>'
            f'<span class="vline"></span><span class="dot {css_class}"></span>'
            f'<span class="tip" role="status"></span></div>')


def make_cell(it):
    labels = {"5d": "5일", "3mo": "3개월"}
    change = ""
    if it.get("change"):
        change = f'<span class="chg {direction(it["change"])}">전일 대비 {esc(it["change"])}</span>'
    elif it.get("note"):
        change = f'<span class="chg flat">{esc(it["note"])}</span>'
    charts = ""
    for key in ("5d", "3mo"):
        tr = it["trends"].get(key)
        if not tr:
            continue
        d = direction(tr["change"])
        charts += f"""
          <div class="trend r-{key}">
            {sparkline(tr, d, it['unit'], it['digits'])}
            <span class="chg {d}">{labels[key]} {esc(tr['change'])}</span>
          </div>"""
    return f"""
        <div class="cell">
          <span class="name">{esc(it['name'])}</span>
          <span class="value">{esc(it['value'])}</span>
          {change}{charts}
        </div>"""


def make_market(data):
    """묶음(금리/환율/주식/원자재·심리)별로 지표 칸을 만들어요."""
    out = []
    for g in data["groups"]:
        rates = ""
        if g["name"] == "금리":
            rates = '\n        <div class="rates">' + "".join(
                f"""
          <div class="cell rate">
            <span class="name">{esc(r['name'])}</span>
            <span class="value">{esc(r['value'])}</span>
          </div>""" for r in data["rates"]) + "\n        </div>"
        cells = "".join(make_cell(it) for it in g["items"])
        out.append(f"""
    <div class="group">
      <h3 class="gname">{esc(g['name'])}</h3>
      <div class="market">{rates}{cells}
      </div>
    </div>""")
    return "".join(out)


def make_signals(found):
    """규칙으로 찾은 신호 카드"""
    if not found:
        body = '\n    <p class="empty">오늘은 평소 범위를 벗어난 뚜렷한 신호가 없어요. 시장이 비교적 잠잠한 상태예요.</p>'
    else:
        cards = []
        for f in found:
            ev = "".join(f"<li>{esc(e)}</li>" for e in f["evidence"])
            cards.append(f"""
    <article class="sig {esc(f['tone'])}">
      <h3>{esc(f['title'])}</h3>
      <p>{esc(f['say'])}</p>
      <ul class="ev">{ev}</ul>
      <p class="watch-line">볼 것: {esc(f['watch'])}</p>
    </article>""")
        body = "".join(cards)
    return f"""<section class="signals">
    <div class="head"><h2>오늘의 신호 <small>최근 {signals.WINDOW}거래일 변화 기준, 규칙 해석</small></h2></div>{body}
  </section>"""


def make_insight(news):
    ins = news.get("insight")
    if not ins:
        return ""  # AI 키가 없으면 해설 칸은 숨겨요 (규칙 신호는 그대로 보여요)
    paras = "".join(f"\n    <p>{esc(p)}</p>" for p in ins.get("situation", []))
    inds = "".join(
        f"\n      <li><b>{esc(i.get('name', ''))}</b> {esc(i.get('comment', ''))}</li>"
        for i in ins.get("indicators", []))
    watch = "".join(
        f"\n      <li><b>{esc(w.get('title', ''))}</b><span>{esc(w.get('why', ''))}</span></li>"
        for w in ins.get("watch", []))
    return f"""<section class="insight">
    <div class="head"><h2>오늘의 해설 <small>AI 작성, {esc(news.get('insight_time', ''))} 지표 기준</small></h2></div>
    <p class="lead">{esc(ins.get('headline', ''))}</p>{paras}
    <h3>지표 읽기</h3>
    <ul class="reads">{inds}
    </ul>
    <h3>앞으로 볼 것</h3>
    <ol class="watch">{watch}
    </ol>
  </section>"""


def make_page(news, indicators, found, war, now):
    with open("template.html", encoding="utf-8") as f:
        template = f.read()
    date_text = f"{now.month}월 {now.day}일 {'월화수목금토일'[now.weekday()]}요일"
    page = (template
            .replace("{{DATE}}", date_text)
            .replace("{{INSIGHT}}", make_insight(news))
            .replace("{{SIGNALS}}", make_signals(found))
            .replace("{{WAR}}", make_rows(war))
            .replace("{{WAR_TIME}}", now.strftime("%H:%M"))
            .replace("{{MARKET_TIME}}", now.strftime("%H:%M"))
            .replace("{{NEWS_TIME}}", news["updated"])
            .replace("{{MARKET}}", make_market(indicators))
            .replace("{{KOREA}}", make_rows(news["korea"]))
            .replace("{{WORLD}}", make_rows(news["world"])))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("index.html 완성")


if __name__ == "__main__":
    now = datetime.now(KST)
    indicators = market.get_all()
    found = signals.detect(indicators)
    war = get_war()
    make_page(get_news(now, indicators, found, war), indicators, found, war, now)
