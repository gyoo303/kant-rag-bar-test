from kant_rag.mcq.textsolve import parse_answers, parse_pasted

TWO = """1쪽
문  1.
대리에 관한 설명 중 옳은 것을 모두 고른 것은?
ㄱ. 가 진술
ㄴ. 나 진술
ㄷ. 다 진술
① ㄱ
② ㄴ
③ ㄱ, ㄴ
④ ㄴ, ㄷ
⑤ ㄱ, ㄴ, ㄷ
문  2.
옳지 않은 것은?
① 하나 ② 둘 ③ 셋
④ 넷 ⑤ 다섯
문  3.
보기가 모자란 문항
① 하나 ② 둘
"""


def test_parse_pasted_multi_and_skip_bad():
    qs, problems = parse_pasted(TWO)
    assert [q.number for q in qs] == [1, 2]
    assert set(qs[0].items) == {"ㄱ", "ㄴ", "ㄷ"} and qs[1].options[5] == "다섯"
    assert len(problems) == 1 and "문  3" in problems[0]


def test_parse_pasted_without_header():
    qs, _ = parse_pasted("옳은 것은?\n① 가 ② 나 ③ 다 ④ 라 ⑤ 마")
    assert len(qs) == 1 and qs[0].number == 1


def test_parse_answers(tmp_path):
    assert parse_answers("3,5, 1") == {1: 3, 2: 5, 3: 1}
    f = tmp_path / "a.csv"
    f.write_text("number,answer\n7,2\n", encoding="utf-8")
    assert parse_answers(str(f)) == {7: 2}
    assert parse_answers(None) == {}
