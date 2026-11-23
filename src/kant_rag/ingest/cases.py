"""판례 수집·청킹.

평가 누수 방지: 검색 주제어는 **시험 문항이 아니라 수집한 법령의 구조**(편/장/절/관 제목, 조문 제목)에서
자동 생성합니다 → data/cases/topics.txt (팀이 검토·추가 가능, 시험 문장 금지).
수집 결과: data/raw/cases/cases.jsonl (판결요지·판시사항·참조조문만, 판례 본문 전체는 저장하지 않음)
청크: 판결요지 항목([1], [2]…) 단위, ID = CASE#<사건번호>#<항목번호>
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kant_rag.ingest.statute import chunk_statute
from kant_rag.schemas import Chunk, DocumentMeta

TAG = re.compile(r"<[^>]+>")
ITEM_SPLIT = re.compile(r"\[(\d+)\]")
GENERIC = {"목적", "정의", "삭제", "시행일", "적용범위", "적용 범위", "준용", "다른 법률과의 관계", "벌칙", "과태료", "경과조치"}


def _clean(s) -> str:
    s = TAG.sub("", str(s or "")).replace("&nbsp;", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def build_topics(statutes: list[tuple[DocumentMeta, str]], level: str = "article") -> list[str]:
    """법령 구조 → 검색 주제어. level=section: 편/장/절/관 제목만, article: + 조문 제목."""
    topics: dict[str, None] = {}
    for meta, text in statutes:
        for c in chunk_statute(text, meta, chunk_size=100000):
            for part in (c.section or "").split(" > ")[:-1]:
                name = re.sub(r"^제\d+(편|장|절|관)\s*", "", part).strip()
                if name and name not in GENERIC:
                    topics[name] = None
            title = c.metadata.get("article_title", "")
            if level == "article" and title and title not in GENERIC and len(title) >= 2:
                topics[title] = None
    return list(topics)


def collect_cases(api, topics: list[str], out_path: Path, date_from: str, date_to: str,
                  per_topic: int = 5, log_every: int = 50) -> dict:
    """주제어별 최신 대법원 판례 per_topic 건. 이미 받은 판례는 건너뜀(재시작 가능)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            seen.add(json.loads(line)["prec_id"])
    stats = {"topics": len(topics), "new": 0, "skipped_existing": len(seen), "no_summary": 0, "errors": 0}
    with out_path.open("a", encoding="utf-8") as f:
        for i, topic in enumerate(topics, 1):
            try:
                hits = api.search_precs(topic, date_from, date_to, display=per_topic * 2)
            except Exception as e:
                stats["errors"] += 1
                print(f"[warn] 검색 실패 '{topic}': {e}")
                continue
            taken = 0
            for h in hits:
                pid = str(h.get("판례일련번호", ""))
                if not pid or pid in seen:
                    taken += pid in seen
                    continue
                if taken >= per_topic:
                    break
                try:
                    d = api.prec(pid)
                except Exception as e:
                    stats["errors"] += 1
                    print(f"[warn] 판례 {pid} 실패: {e}")
                    continue
                summary = _clean(d.get("판결요지"))
                if not summary:
                    stats["no_summary"] += 1
                    seen.add(pid)
                    continue
                rec = {
                    "prec_id": pid, "case_no": _clean(d.get("사건번호")), "case_name": _clean(d.get("사건명")),
                    "court": _clean(d.get("법원명")), "decided": _clean(d.get("선고일자")),
                    "holding_issue": _clean(d.get("판시사항")), "summary": summary,
                    "ref_articles": _clean(d.get("참조조문")), "ref_cases": _clean(d.get("참조판례")),
                    "topic": topic,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                seen.add(pid)
                taken += 1
                stats["new"] += 1
            if i % log_every == 0:
                f.flush()
                print(f"  {i}/{len(topics)} 주제어, 신규 {stats['new']}건")
    return stats


def _split_items(text: str) -> list[tuple[str, str]]:
    parts = ITEM_SPLIT.split(text)
    if len(parts) < 3:
        return [("1", text.strip())]
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2) if parts[i + 1].strip()]


def chunk_cases(jsonl_path: Path, meta: DocumentMeta, date_to: str | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    seen_ids: set[str] = set()
    for line_no, line in enumerate(jsonl_path.open(encoding="utf-8"), start=1):
        c = json.loads(line)
        decided = re.sub(r"\D", "", c.get("decided", ""))
        if date_to and decided and decided > date_to:  # 시험일 이후 판례 제외
            continue
        issues = dict(_split_items(c.get("holding_issue", "")))
        label = f"{c['court']} {c['decided']} {c['case_no']}"
        for n, body in _split_items(c["summary"]):
            cid = f"CASE#{c['case_no'] or c['prec_id']}#{n}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            issue = issues.get(n, "")
            text = f"[판례] {label} 판결요지 [{n}]\n" + (f"판시사항: {issue}\n" if issue else "") + body
            if c.get("ref_articles"):
                text += f"\n참조조문: {c['ref_articles']}"
            chunks.append(Chunk(
                chunk_id=cid, doc_id=meta.doc_id, title=f"{c['court']} {c['case_no']}", text=text,
                section=f"{label} 판결요지 [{n}]", line_start=line_no, line_end=line_no,
                metadata={"doc_type": "case", "case_no": c["case_no"], "decided": c["decided"],
                          "prec_id": c["prec_id"], "topic": c.get("topic"), "source": meta.source},
            ))
    return chunks
