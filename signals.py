# ============================================================
#  규칙 기반 신호 해석 (AI 없이, 비용 0원)
#
#  방법: 각 지표의 '최근 5거래일 변화'가 지난 3개월 동안의
#  '평소 5일 변화 폭'에 비해 얼마나 큰지 계산해서
#    평소의 1배 이상 오르면 up, 2배 이상이면 big_up
#    평소의 1배 이상 내리면 down, 2배 이상이면 big_down
#    그 사이면 flat
#  으로 상태를 정하고, 아래 RULES 와 맞는 조합을 찾아 해석을 보여줘요.
# ============================================================

import statistics

# ------------------------------------------------------------
# [설정]
# ------------------------------------------------------------

WINDOW = 5          # 며칠 변화를 볼지 (거래일)
THRESHOLD = 1.0     # 평소의 몇 배 이상이면 '움직였다'고 볼지
BIG = 2.0           # 평소의 몇 배 이상이면 '크게 움직였다'고 볼지
CURVE_BP = 5        # 2년물과 10년물 변화 차이가 몇 bp 이상이면 커브 변화로 볼지

# 상태 이름
#   up / down / flat / big_up / big_down
#   not_up(오르지 않음) / not_down(내리지 않음)
#   "커브": bear_flat / bear_steep / bull_steep / bull_flat
#   "장단기 금리차": inverted / normal
#
# tone: warn(경계) / good(우호) / info(참고)
RULES = [
    # ---------------- 금리 ----------------
    {"when": {"커브": "bear_flat"}, "tone": "warn",
     "title": "긴축 기대 강화",
     "say": "단기금리(2년물)가 장기금리보다 더 올랐어요. 시장이 연준의 추가 인상이나 긴축 장기화를 더 많이 반영하고 있다는 뜻이에요.",
     "watch": "연준 위원 발언, 다음 CPI와 고용지표"},
    {"when": {"커브": "bear_steep"}, "tone": "warn",
     "title": "장기금리 부담 확대",
     "say": "장기금리(10년물)가 단기금리보다 더 올랐어요. 인플레이션이나 미국 재정 적자 우려로 장기채를 기피하는 흐름이라, 성장주 중심으로 증시 밸류에이션 부담이 커질 수 있어요.",
     "watch": "미 국채 입찰 결과, 재정 관련 뉴스"},
    {"when": {"커브": "bull_steep"}, "tone": "info",
     "title": "금리 인하 기대 확대",
     "say": "단기금리가 장기금리보다 더 많이 내렸어요. 시장이 금리 인하를 앞당겨 반영하는 중인데, 경기 둔화 걱정이 함께 있는지 확인이 필요해요.",
     "watch": "고용지표, 실업률 추이"},
    {"when": {"커브": "bull_flat"}, "tone": "warn",
     "title": "장기 성장 기대 약화",
     "say": "장기금리가 단기금리보다 더 많이 내렸어요. 안전자산 선호가 커지거나 장기 경기 전망이 어두워지는 흐름일 수 있어요.",
     "watch": "주가와 VIX가 같이 흔들리는지"},
    {"when": {"장단기 금리차": "inverted"}, "tone": "warn",
     "title": "장단기 금리 역전",
     "say": "10년물 금리가 2년물보다 낮아요. 과거 경기침체에 앞서 자주 나타난 신호지만, 역전 후 침체까지는 시차가 길고 예외도 있어요.",
     "watch": "역전 폭이 커지는지, 다시 풀리는지"},
    {"when": {"미국 10년물": "big_up"}, "tone": "warn",
     "title": "미국 장기금리 급등",
     "say": "10년물이 평소보다 훨씬 크게 올랐어요. 금리가 빠르게 오르면 주식 가치 계산이 불리해지고, 달러 강세로 신흥국 자금 이탈 압력도 커져요.",
     "watch": "코스피 외국인 수급, 원/달러"},

    # ---------------- 환율 ----------------
    {"when": {"원/달러": "up", "달러인덱스": "up"}, "tone": "info",
     "title": "글로벌 달러 강세",
     "say": "원/달러가 오르는 건 달러가 전 세계적으로 강해진 영향이 커요. 원화만의 문제라기보다 미국 금리와 달러 흐름을 봐야 해요.",
     "watch": "미국 금리, 연준 기대"},
    {"when": {"원/달러": "up", "달러인덱스": "not_up"}, "tone": "warn",
     "title": "원화 고유 약세",
     "say": "달러는 잠잠한데 원화만 약해지고 있어요. 외국인 주식 매도, 무역수지, 국내 정책 같은 한국 쪽 요인을 확인해볼 때예요.",
     "watch": "외국인 순매도, 수출입 통계"},
    {"when": {"원/달러": "up", "위안/달러": "up"}, "tone": "info",
     "title": "위안화 동조 약세",
     "say": "원화와 위안화가 같이 약해지고 있어요. 원화는 위안화와 함께 움직이는 경향이 강해서, 중국 경기나 정책 소식이 원화에도 영향을 주는 국면이에요.",
     "watch": "중국 경제지표, 인민은행 고시환율"},
    {"when": {"원/달러": "down", "달러인덱스": "down"}, "tone": "good",
     "title": "달러 약세에 원화 강세",
     "say": "달러가 전반적으로 약해지면서 원화가 강해지고 있어요. 외국인 자금 유입에 우호적인 환경이에요.",
     "watch": "코스피 외국인 수급"},
    {"when": {"엔/달러": "big_down", "VIX 공포지수": "up"}, "tone": "warn",
     "title": "엔캐리 청산 경계",
     "say": "엔화가 급하게 강해지면서 시장 불안도 커지고 있어요. 싼 엔화로 빌려 투자했던 자금이 되돌려지면 글로벌 증시가 크게 흔들릴 수 있어요(2024년 8월 사례).",
     "watch": "일본은행 발언, 닛케이 급락 여부"},
    {"when": {"엔/달러": "big_up"}, "tone": "info",
     "title": "엔화 급약세",
     "say": "엔화가 빠르게 약해지고 있어요. 일본과 경쟁하는 한국 수출 기업(자동차, 기계 등)의 가격 경쟁력에는 부담이에요.",
     "watch": "일본 당국 개입 발언"},

    # ---------------- 주식·심리 ----------------
    {"when": {"S&P 500": "down", "VIX 공포지수": "up", "미국 10년물": "down", "금": "not_down"}, "tone": "warn",
     "title": "위험회피 국면",
     "say": "주식은 빠지고, 공포지수는 오르고, 돈이 국채와 금으로 피하고 있어요. 전형적인 위험회피 흐름이에요.",
     "watch": "VIX가 계속 오르는지, 신용시장 불안 소식"},
    {"when": {"S&P 500": "up", "VIX 공포지수": "down"}, "tone": "good",
     "title": "위험선호 국면",
     "say": "주가가 오르고 공포지수는 내려가는, 투자 심리가 좋은 흐름이에요.",
     "watch": "너무 빠른 상승 뒤 금리 반응"},
    {"when": {"S&P 500": "down", "미국 10년물": "up"}, "tone": "warn",
     "title": "금리발 증시 조정",
     "say": "금리가 오르면서 주가가 밀리고 있어요. 경기 걱정보다는 금리 부담 때문에 빠지는 조정이라, 금리가 안정되는지가 관건이에요.",
     "watch": "10년물 추이, 연준 기대"},
    {"when": {"코스피": "down", "원/달러": "up"}, "tone": "warn",
     "title": "외국인 이탈형 약세",
     "say": "코스피가 빠지면서 원/달러는 오르고 있어요. 외국인이 주식을 팔고 달러로 바꿔 나가는 전형적인 모습일 수 있어요.",
     "watch": "외국인 순매도 규모"},
    {"when": {"코스피": "down", "S&P 500": "not_down"}, "tone": "info",
     "title": "국내 증시 상대 약세",
     "say": "미국 증시는 버티는데 코스피만 약해요. 반도체 업황, 국내 정책, 원화 약세 같은 한국 쪽 요인이 더 크게 작용하는 중이에요.",
     "watch": "반도체 관련 뉴스, 외국인 수급"},
    {"when": {"VIX 공포지수": "big_up"}, "tone": "warn",
     "title": "변동성 급등",
     "say": "공포지수가 평소보다 훨씬 크게 뛰었어요. 시장이 갑자기 불안해졌다는 뜻이라, 무엇이 촉발했는지 뉴스를 확인해보세요.",
     "watch": "VIX가 며칠 안에 진정되는지"},

    # ---------------- 원자재 ----------------
    {"when": {"구리": "up", "WTI 유가": "up", "미국 10년물": "up"}, "tone": "info",
     "title": "경기 회복 기대 (리플레이션)",
     "say": "구리, 유가, 금리가 함께 오르고 있어요. 시장이 경기 회복과 물가 상승을 같이 예상하는 흐름이에요.",
     "watch": "물가 지표가 따라 오르는지"},
    {"when": {"WTI 유가": "up", "미국 10년물": "up", "구리": "not_up"}, "tone": "warn",
     "title": "물가 걱정형 금리 상승",
     "say": "유가와 금리는 오르는데 경기를 반영하는 구리는 잠잠해요. 경기가 좋아서라기보다 물가 걱정으로 금리가 오르는 쪽에 가까워요.",
     "watch": "기대인플레이션, CPI"},
    {"when": {"WTI 유가": "big_up"}, "tone": "warn",
     "title": "유가 급등",
     "say": "유가가 크게 올랐어요. 원유를 전량 수입하는 한국에는 물가와 무역수지 모두 부담이에요.",
     "watch": "국내 물가, 무역수지 발표"},
    {"when": {"구리/금 비율": "down"}, "tone": "warn",
     "title": "경기 비관 심리",
     "say": "경기에 민감한 구리가 안전자산인 금보다 약해요. 시장이 경기를 비관적으로 보기 시작했다는 신호예요.",
     "watch": "제조업 지표(PMI), 중국 경기"},
    {"when": {"구리/금 비율": "down", "미국 10년물": "up"}, "tone": "warn",
     "title": "금리와 경기 신호 엇갈림",
     "say": "경기 신호(구리/금 비율)는 약해지는데 금리는 오르고 있어요. 경기에 비해 금리가 높아지는 상황이라, 시간이 지나면 금리가 꺾이거나 경기가 더 눌릴 수 있어요.",
     "watch": "둘 중 어느 쪽이 먼저 방향을 바꾸는지"},

    # ---------------- 금 ----------------
    {"when": {"금": "up", "미국 10년물": "down"}, "tone": "info",
     "title": "금리 하락에 금 강세",
     "say": "금리가 내려가며 이자를 안 주는 금의 매력이 커졌어요. 교과서적인 정상 흐름이에요.",
     "watch": "금리 인하 기대가 이어지는지"},
    {"when": {"금": "down", "미국 10년물": "up", "달러인덱스": "up"}, "tone": "info",
     "title": "긴축 압박에 금 약세",
     "say": "금리와 달러가 함께 오르며 금이 눌리고 있어요. 긴축 분위기에서 흔히 나타나는 흐름이에요.",
     "watch": "연준 기대 변화"},
    {"when": {"금": "up", "미국 10년물": "up"}, "tone": "warn",
     "title": "금리를 무시한 금 강세",
     "say": "원래 금리가 오르면 금은 약해지는데 둘 다 오르고 있어요. 인플레이션 대비, 중앙은행들의 금 매수, 달러 자산에 대한 불신 같은 구조적 수요가 강하다는 신호예요.",
     "watch": "중앙은행 금 매입 뉴스, 기대인플레이션"},
    {"when": {"금": "up", "달러인덱스": "up"}, "tone": "warn",
     "title": "달러와 금 동반 강세",
     "say": "보통 반대로 움직이는 달러와 금이 같이 오르고 있어요. 지정학 불안 등으로 안전자산 쏠림이 강하다는 뜻이에요.",
     "watch": "지정학 관련 뉴스"},
    {"when": {"금": "up", "S&P 500": "up"}, "tone": "info",
     "title": "주식과 금 동반 상승",
     "say": "위험자산과 안전자산이 같이 오르고 있어요. 시중에 돈이 많이 풀렸거나, 화폐 가치 하락을 대비하는 수요가 있다는 뜻일 수 있어요.",
     "watch": "유동성 관련 정책, 달러 흐름"},
    {"when": {"금": "down", "VIX 공포지수": "big_up", "S&P 500": "down"}, "tone": "warn",
     "title": "투매 신호",
     "say": "급락장에서 안전자산인 금까지 팔리고 있어요. 손실을 메우려고 현금을 확보하는 투매가 나올 때 보이는 모습이에요(2020년 3월 초).",
     "watch": "중앙은행의 긴급 대응 여부"},
    {"when": {"금": "up", "WTI 유가": "up"}, "tone": "warn",
     "title": "지정학 리스크 반영",
     "say": "금과 유가가 함께 오르고 있어요. 중동 등 지정학적 긴장이 가격에 반영되는 전형적인 조합이에요.",
     "watch": "중동 정세, 원유 공급 뉴스"},
    {"when": {"원화 금값": "up", "원/달러": "up"}, "tone": "info",
     "title": "원화 기준 금값 이중 상승",
     "say": "국제 금값에 원화 약세까지 겹쳐 국내 투자자가 체감하는 금값이 더 크게 올랐어요. 반대로 환율이 꺾이면 국제 금값이 그대로여도 국내 금값은 빠질 수 있어요.",
     "watch": "원/달러 방향"},
]

# ------------------------------------------------------------
# 아래부터는 동작 부분 (안 건드려도 돼요)
# ------------------------------------------------------------


def _measure(values):
    """최근 WINDOW일 변화와, 그게 평소의 몇 배인지(z)를 계산해요."""
    if len(values) < WINDOW * 3:
        return None
    changes = [values[i] - values[i - WINDOW] for i in range(WINDOW, len(values))]
    sd = statistics.pstdev(changes)
    if sd == 0:
        return None
    cur = values[-1] - values[-1 - WINDOW]
    return {"diff": cur, "base": values[-1 - WINDOW], "z": cur / sd}


def _state(z):
    if z >= BIG:
        return "big_up"
    if z >= THRESHOLD:
        return "up"
    if z <= -BIG:
        return "big_down"
    if z <= -THRESHOLD:
        return "down"
    return "flat"


def _daily(item):
    """지표의 3개월 일별 (날짜 → 값)"""
    tr = item.get("trends", {}).get("3mo")
    if not tr:
        return {}
    return dict(zip(tr["times"], tr["values"]))


def _combine(a, b, fn):
    """두 지표를 날짜를 맞춰 계산한 새 값 목록"""
    days = sorted(set(a) & set(b))
    return [fn(a[d], b[d]) for d in days]


def build_states(indicators):
    """모든 지표의 상태(up/down/...)와 근거를 만들어요."""
    items = {it["name"]: it for g in indicators["groups"] for it in g["items"]}
    info = {}

    for name, it in items.items():
        tr = it.get("trends", {}).get("3mo")
        if not tr:
            continue
        m = _measure(tr["values"])
        if m:
            m["unit"] = it["unit"]
            info[name] = m

    # 안에서만 쓰는 계산 지표
    gold, copper, krw = (_daily(items.get(n, {})) for n in ("금", "구리", "원/달러"))
    if gold and copper:
        m = _measure(_combine(copper, gold, lambda c, g: c / g))
        if m:
            m["unit"] = "ratio"
            info["구리/금 비율"] = m
    if gold and krw:
        m = _measure(_combine(gold, krw, lambda g, k: g * k / 31.1035))  # 원/그램
        if m:
            m["unit"] = "ratio"
            info["원화 금값"] = m

    states = {name: _state(m["z"]) for name, m in info.items()}

    # 장단기 금리차 (현재 값)
    spread = items.get("장단기 금리차")
    if spread and spread.get("price") is not None:
        states["장단기 금리차"] = "inverted" if spread["price"] < 0 else "normal"

    # 커브 모양 변화 (2년물과 10년물의 5일 변화 비교, bp)
    if "미국 10년물" in info and "미국 2년물" in info:
        d10 = info["미국 10년물"]["diff"] * 100
        d2 = info["미국 2년물"]["diff"] * 100
        curve = None
        if d2 > 0 and d10 > 0:
            if d2 - d10 >= CURVE_BP:
                curve = "bear_flat"
            elif d10 - d2 >= CURVE_BP:
                curve = "bear_steep"
        elif d2 < 0 and d10 < 0:
            if d10 - d2 >= CURVE_BP:
                curve = "bull_steep"
            elif d2 - d10 >= CURVE_BP:
                curve = "bull_flat"
        if curve:
            states["커브"] = curve
            info["커브"] = {"text": f"2년물 {d2:+.0f}bp, 10년물 {d10:+.0f}bp"}
    return states, info


def _match(want, have):
    if have is None:
        return False
    if want == "up":
        return have in ("up", "big_up")
    if want == "down":
        return have in ("down", "big_down")
    if want == "not_up":
        return have not in ("up", "big_up")
    if want == "not_down":
        return have not in ("down", "big_down")
    return want == have


def _evidence(name, m):
    """'원/달러 5일 +1.2% (평소의 1.8배)' 같은 근거 글"""
    if "text" in m:
        return m["text"]
    if name == "장단기 금리차":
        return None
    if m["unit"] == "%":
        move = f"{m['diff'] * 100:+.0f}bp"
    else:
        move = f"{m['diff'] / m['base'] * 100:+.1f}%" if m["base"] else f"{m['diff']:+.2f}"
    return f"{name} {WINDOW}일 {move} (평소 움직임의 {abs(m['z']):.1f}배)"


def detect(indicators):
    """규칙과 맞는 신호 목록을 돌려줘요."""
    states, info = build_states(indicators)
    found = []
    for rule in RULES:
        if all(_match(want, states.get(name)) for name, want in rule["when"].items()):
            ev = [e for e in (_evidence(n, info[n]) for n in rule["when"] if n in info) if e]
            found.append({**{k: rule[k] for k in ("title", "say", "watch", "tone")}, "evidence": ev})
    print(f"[신호] {len(found)}개 감지: " + ", ".join(f["title"] for f in found))
    return found
