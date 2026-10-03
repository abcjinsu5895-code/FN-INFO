# ============================================================
#  AI 해설 만들기 (Claude API)
#   지표 + 오늘 고른 기사 6개를 보여주고
#   현재 상황 해석과 앞으로 볼 포인트를 써달라고 요청해요.
#   ANTHROPIC_API_KEY 가 없으면 아무것도 안 하고 넘어가요.
# ============================================================

import json
import os
import urllib.request

# ------------------------------------------------------------
# [설정]
# ------------------------------------------------------------

MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = """너는 개인 투자자에게 매일 아침 거시경제 브리핑을 써주는 애널리스트야.

원칙:
- 아래에 주어진 지표 숫자와 기사 제목만 근거로 써. 주어지지 않은 숫자나 사실을 지어내지 마.
- 기사는 제목만 있으니, 제목에서 확실히 알 수 있는 것 이상은 단정하지 말고 "~로 보인다" 정도로 써.
- [규칙으로 감지된 신호]는 미리 정한 규칙으로 찾은 것이니, 이를 출발점으로 삼되 기사와 엮어 우선순위를 정해줘.
- 전쟁·지정학 기사(휴전, 종전 협상 등)가 유가, 금, 달러, 증시에 어떻게 반영되고 있는지 반드시 짚어줘.
- 지표들 사이의 연결(예: 금리와 환율, 유가와 물가, 미국채 금리와 주가)을 짚어서 "그래서 지금 무슨 국면인지"를 설명해.
- 특정 종목 매수/매도 같은 투자 권유는 하지 마.
- 쉬운 한국어로, 경제 기사를 즐겨 읽는 일반인이 이해할 수 있게 써.

반드시 아래 형식의 JSON만 출력해. 앞뒤에 다른 글이나 ``` 표시를 붙이지 마.
{
  "headline": "오늘 상황을 한 문장으로 (40자 안팎)",
  "situation": ["현재 상황 해설 문단", "..."],
  "indicators": [{"name": "지표 이름", "comment": "이 지표가 지금 말해주는 것 1~2문장"}],
  "watch": [{"title": "짧은 제목", "why": "왜 중요한지, 언제 무엇을 확인하면 되는지"}]
}
- situation은 2~3문단, 각 문단 3~4문장.
- indicators는 오늘 눈여겨볼 만한 지표 3~5개만. 달러인덱스와 원/달러, 위안/달러를 비교해 원화 움직임이 달러 강세 때문인지 원화 고유 요인인지, 장단기 금리차와 VIX로 시장 분위기가 어떤지 같이 짚어줘.
- watch는 중요한 순서대로 정확히 3개."""

# ------------------------------------------------------------


def _describe(indicators, news, today, found=None, war=None):
    """AI에게 보여줄 오늘의 자료를 글로 정리해요."""
    lines = [f"오늘 날짜: {today}", "", "[기준금리]"]
    for r in indicators["rates"]:
        lines.append(f"- {r['name']}: {r['value']}")
    for g in indicators["groups"]:
        lines += ["", f"[{g['name']}]"]
        for q in g["items"]:
            parts = [f"현재 {q['value']}"]
            if q.get("note"):
                parts.append(q["note"])
            if q["change"]:
                parts.append(f"전일 대비 {q['change']}")
            for key, label in (("5d", "5일"), ("3mo", "3개월")):
                if key in q["trends"]:
                    t = q["trends"][key]
                    parts.append(f"{label} 변화 {t['change']} "
                                 f"(기간 최저 {min(t['values']):,.2f}, 최고 {max(t['values']):,.2f})")
            lines.append(f"- {q['name']}: " + ", ".join(parts))
    lines += ["", "[규칙으로 감지된 신호]"]
    for f in found or []:
        lines.append(f"- {f['title']}: {f['say']} (근거: {', '.join(f['evidence'])})")
    if not found:
        lines.append("- 없음 (평소 범위 안에서 움직임)")
    for label, items in (("전쟁·지정학 최신 기사", war or []),
                         ("국내 경제 기사", news.get("korea", [])),
                         ("해외 경제 기사", news.get("world", []))):
        lines += ["", f"[{label}]"]
        for a in items:
            lines.append(f"- ({a['topic']}) {a['title']} / {a['source']} {a.get('time', '')}")
    return "\n".join(lines)


def make_insight(indicators, news, today, found=None, war=None):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("[해설] API 키가 없어서 건너뜀")
        return None

    body = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _describe(indicators, news, today, found, war)}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            data = json.loads(res.read())
        text = "".join(b.get("text", "") for b in data["content"])
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        print("[해설] 작성 완료")
        return result
    except Exception as e:
        print(f"[해설] 실패: {e}")
        return None
