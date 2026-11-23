from civil_rag.exam.solver import choice_expectation, format_question, split_statements, stem_polarity


def test_split_statements_joins_wrapped_lines():
    p = "ㄱ. 첫째 지문\n이어지는 줄\nㄴ. 둘째 지문"
    assert split_statements(p) == {"ㄱ": "첫째 지문 이어지는 줄", "ㄴ": "둘째 지문"}


def test_choice_expectation_patterns():
    letters = ["ㄱ", "ㄴ", "ㄷ", "ㄹ"]
    assert choice_expectation("ㄱ(○), ㄴ(×), ㄷ(○), ㄹ(×)", letters, "unknown") == {"ㄱ": "O", "ㄴ": "X", "ㄷ": "O", "ㄹ": "X"}
    assert choice_expectation("ㄱ, ㄷ", letters, "correct") == {"ㄱ": "O", "ㄴ": "X", "ㄷ": "O", "ㄹ": "X"}
    assert choice_expectation("ㄱ, ㄷ", letters, "incorrect") == {"ㄱ": "X", "ㄴ": "O", "ㄷ": "X", "ㄹ": "O"}
    assert choice_expectation("ㄱ, ㄷ", letters, "unknown") is None


def test_stem_polarity():
    assert stem_polarity("…에 관한 설명으로 옳지 않은 것은?") == "incorrect"
    assert stem_polarity("…에 관한 설명으로 틀린 것은?") == "incorrect"
    assert stem_polarity("…에 관한 설명으로 옳은 것은?") == "correct"
    assert stem_polarity("다음 중 甲이 청구할 수 있는 금액은?") == "unknown"


def test_format_question_orders_choices_and_marks():
    q = format_question({"stem": "옳은 것은?", "choices": {"2": "나", "1": "가", "3": "다", "4": "라", "5": "마"}})
    assert q.splitlines() == ["옳은 것은?", "① 가", "② 나", "③ 다", "④ 라", "⑤ 마"]
