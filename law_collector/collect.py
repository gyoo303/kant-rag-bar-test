"""
국가법령정보 공동활용(open.law.go.kr) 민사 판례·법령 수집기

팀원 여러 명이 각자 자기 OC로, 하루 한도(기본 10,000회) 안에서 나눠 수집한다.
- 분담 기준: 판례일련번호 % 인원수  → 누가 언제 돌려도 담당 범위가 겹치지 않음
- 이어받기: 이미 저장된 판례는 건너뜀 (중간에 끊겨도 다시 실행하면 이어서 진행)
- 일일 한도: 오늘 호출 수를 state/ 에 기록, 한도에 닿으면 자동 종료

사용법 (자세한 건 README.md):
    python collect.py list                 # 1) 민사 판례 ID 목록 만들기
    python collect.py fetch --member 1     # 2) 내 담당 판례 본문 받기 (1/2/3)
    python collect.py laws                 # 3) 민법 등 조문 받기 (한 명만)
    python collect.py status               # 진행 상황
표준 라이브러리만 사용 (pip install 불필요). Python 3.9+
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://www.law.go.kr/DRF"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATE = ROOT / "state"
IDS_FILE = DATA / "civil_ids.jsonl"
PREC_DIR = DATA / "prec"
LAW_DIR = DATA / "law"
FAILED_FILE = STATE / "failed.jsonl"

CIVIL_CODE = "400101"  # 사건종류코드: 민사
PAGE_SIZE = 100        # 목록 API 한 번에 최대 100건

# 변호사시험 민사법 범위에서 주로 쓰는 법령 (필요하면 추가)
CIVIL_LAWS = [
    "민법",
    "민사소송법",
    "민사집행법",
    "상법",
    "주택임대차보호법",
    "상가건물 임대차보호법",
    "가등기담보 등에 관한 법률",
    "집합건물의 소유 및 관리에 관한 법률",
    "부동산등기법",
    "부동산 실권리자명의 등기에 관한 법률",
    "이자제한법",
    "제조물 책임법",
    "약관의 규제에 관한 법률",
    "신탁법",
    "어음법",
    "수표법",
]

try:
    sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 콘솔 한글 깨짐 방지
except Exception:
    pass


# ───────────────────────── 설정 ─────────────────────────
def load_env() -> None:
    """같은 폴더의 .env 를 읽어 환경변수로 (python-dotenv 없이)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
OC = os.environ.get("LAW_OC", "").strip()
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "10000"))
DELAY = float(os.environ.get("REQUEST_DELAY", "0.5"))
MEMBERS = int(os.environ.get("MEMBERS", "3"))


class StopCollecting(Exception):
    """더 진행하면 안 되는 상황 (한도 도달, 인증 실패, 연속 오류)."""


# ─────────────────────── 파일 유틸 ───────────────────────
def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def append_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_ids() -> dict[str, dict]:
    """civil_ids.jsonl → {판례일련번호: 메타} (중복 제거)."""
    out: dict[str, dict] = {}
    if IDS_FILE.exists():
        with IDS_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    out[str(r["id"])] = r
    return out


# ───────────────────── 일일 호출 카운터 ─────────────────────
def usage_path() -> Path:
    return STATE / f"usage_{OC}.json"


def today() -> str:
    return dt.date.today().isoformat()


def used_today() -> int:
    return read_json(usage_path(), {}).get(today(), 0)


def add_usage(n: int = 1) -> None:
    u = read_json(usage_path(), {})
    u[today()] = u.get(today(), 0) + n
    write_json_atomic(usage_path(), u)


# ───────────────────────── API 호출 ─────────────────────────
def call(endpoint: str, params: dict) -> dict:
    """API 한 번 호출. 한도·인증·재시도 처리 포함. 성공하면 JSON dict."""
    if used_today() >= DAILY_LIMIT:
        raise StopCollecting(f"오늘 한도 {DAILY_LIMIT}회 도달. 내일 다시 실행하세요.")

    q = {"OC": OC, "type": "JSON", **params}
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(q)}"
    last_err = None
    for attempt in range(1, 4):
        try:
            add_usage(1)  # 실패한 호출도 서버 입장에선 호출이므로 센다
            req = urllib.request.Request(url, headers={"User-Agent": "civil-rag-collector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
            data = json.loads(text)
            if isinstance(data, dict) and "result" in data and "검증" in str(data.get("result")):
                raise StopCollecting(
                    "사용자 인증 실패: OC 값이나 등록한 서버 IP가 맞지 않습니다.\n"
                    "  → open.law.go.kr 마이페이지 > API인증키관리 에서 OC/IP 확인\n"
                    f"  → 서버 메시지: {data.get('msg', '')}"
                )
            time.sleep(DELAY)
            return data
        except StopCollecting:
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last_err = e
            wait = DELAY + 2 ** attempt
            print(f"  ! 호출 오류({attempt}/3): {e} → {wait:.0f}초 후 재시도")
            time.sleep(wait)
    raise RuntimeError(f"3회 재시도 실패: {last_err}")


# ───────────────────────── 1) 목록 ─────────────────────────
def cmd_list(args) -> None:
    """전체 판례 목록을 선고일자 오름차순으로 훑으며 민사(400101)만 civil_ids.jsonl 에 저장."""
    prog_path = STATE / "list_progress.json"
    prog = read_json(prog_path, {"last_page": 0, "total_pages": None})

    if prog["total_pages"] is None:
        first = call("lawSearch.do", {"target": "prec", "display": 1, "sort": "dasc"})
        total = int(first["PrecSearch"]["totalCnt"])
        prog["total_pages"] = (total + PAGE_SIZE - 1) // PAGE_SIZE
        write_json_atomic(prog_path, prog)
        print(f"전체 판례 {total:,}건 → {prog['total_pages']:,}페이지")

    total_pages = prog["total_pages"]
    start = prog["last_page"] + 1
    if start > total_pages:
        print(f"목록 수집 이미 완료. 민사 {len(read_ids()):,}건 (data/civil_ids.jsonl)")
        return

    end = min(total_pages, start + args.max_pages - 1) if args.max_pages else total_pages
    print(f"목록 수집: {start} ~ {end} 페이지 / 전체 {total_pages:,} (오늘 사용 {used_today():,}/{DAILY_LIMIT:,})")
    civil_found = 0
    try:
        for page in range(start, end + 1):
            data = call("lawSearch.do", {"target": "prec", "display": PAGE_SIZE, "page": page, "sort": "dasc"})
            rows = data.get("PrecSearch", {}).get("prec") or []
            if isinstance(rows, dict):  # 결과가 1건이면 dict 로 옴
                rows = [rows]
            civil = [
                {
                    "id": r.get("판례일련번호"),
                    "사건번호": r.get("사건번호"),
                    "사건명": r.get("사건명"),
                    "선고일자": r.get("선고일자"),
                    "법원명": r.get("법원명"),
                    "데이터출처명": r.get("데이터출처명"),
                }
                for r in rows
                if r.get("사건종류코드") == CIVIL_CODE
            ]
            append_jsonl(IDS_FILE, civil)
            civil_found += len(civil)
            prog["last_page"] = page
            write_json_atomic(prog_path, prog)
            if page % 20 == 0 or page == end:
                print(f"  {page:,}/{total_pages:,} 페이지 · 이번 실행 민사 +{civil_found:,} · 오늘 {used_today():,}회")
    except StopCollecting as e:
        print(f"\n중단: {e}")
    except KeyboardInterrupt:
        print("\n사용자 중단. 다시 실행하면 이어서 진행합니다.")
    print(f"민사 판례 누적 {len(read_ids()):,}건 → {IDS_FILE.relative_to(ROOT)}")


# ───────────────────────── 2) 본문 ─────────────────────────
def my_targets(member: int, members: int, source: str | None) -> list[str]:
    ids = read_ids()
    if not ids:
        raise SystemExit("data/civil_ids.jsonl 이 없습니다. 먼저 `python collect.py list` 를 실행하거나 팀원에게 받아 넣으세요.")
    out = []
    for pid, meta in ids.items():
        if not pid or not pid.isdigit():
            continue
        if source and meta.get("데이터출처명") != source:
            continue
        if int(pid) % members == member - 1:
            out.append(pid)
    out.sort(key=int)
    return out


def cmd_fetch(args) -> None:
    member, members = args.member, args.members
    if not 1 <= member <= members:
        raise SystemExit(f"--member 는 1~{members} 사이여야 합니다.")
    targets = my_targets(member, members, args.source)
    todo = [p for p in targets if not (PREC_DIR / f"{p}.json").exists()]
    if args.limit:
        todo = todo[: args.limit]

    print(f"[팀원 {member}/{members}] 담당 {len(targets):,}건 · 남은 {len(todo):,}건 · "
          f"오늘 사용 {used_today():,}/{DAILY_LIMIT:,}"
          + (f" · 출처={args.source}" if args.source else ""))
    if not todo:
        print("내 담당분 수집 완료!")
        return

    done = 0
    consecutive_fail = 0
    t0 = time.time()
    try:
        for pid in todo:
            try:
                data = call("lawService.do", {"target": "prec", "ID": pid})
            except RuntimeError as e:  # 재시도까지 실패
                append_jsonl(FAILED_FILE, [{"id": pid, "error": str(e), "at": dt.datetime.now().isoformat()}])
                consecutive_fail += 1
                if consecutive_fail >= 10:
                    raise StopCollecting("10건 연속 실패. 네트워크/서버 상태를 확인하세요.")
                continue

            body = data.get("PrecService")
            if not body:  # 예: {"Law": "일치하는 판례가 없습니다..."}
                append_jsonl(FAILED_FILE, [{"id": pid, "error": json.dumps(data, ensure_ascii=False)[:200],
                                            "at": dt.datetime.now().isoformat()}])
                continue

            write_json_atomic(PREC_DIR / f"{pid}.json", body)
            consecutive_fail = 0
            done += 1
            if done % 100 == 0:
                rate = done / max(time.time() - t0, 1) * 3600
                print(f"  +{done:,}건 · 오늘 {used_today():,}/{DAILY_LIMIT:,}회 · 약 {rate:,.0f}건/시간")
    except StopCollecting as e:
        print(f"\n중단: {e}")
    except KeyboardInterrupt:
        print("\n사용자 중단. 다시 실행하면 이어서 진행합니다.")
    left = sum(1 for p in targets if not (PREC_DIR / f"{p}.json").exists())
    print(f"이번 실행 {done:,}건 저장 · 내 담당 남은 {left:,}건 · 실패 기록: state/failed.jsonl")


# ───────────────────────── 3) 법령 ─────────────────────────
def cmd_laws(args) -> None:
    names = args.names or CIVIL_LAWS
    LAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for name in names:
            out = LAW_DIR / f"{name.replace(' ', '_')}.json"
            if out.exists():
                print(f"  = {name} (이미 있음)")
                continue
            data = call("lawSearch.do", {"target": "law", "query": name, "display": 100})
            rows = data.get("LawSearch", {}).get("law") or []
            if isinstance(rows, dict):
                rows = [rows]
            hit = next((r for r in rows if r.get("법령명한글") == name and r.get("현행연혁코드") == "현행"), None)
            if not hit:
                print(f"  ? {name}: 정확히 일치하는 현행 법령 없음 (이름 확인)")
                continue
            body = call("lawService.do", {"target": "law", "MST": hit["법령일련번호"]})
            write_json_atomic(out, body)
            print(f"  + {name} (MST {hit['법령일련번호']}, 시행 {hit.get('시행일자')})")
    except StopCollecting as e:
        print(f"\n중단: {e}")


# ───────────────────────── 상태 ─────────────────────────
def cmd_status(args) -> None:
    ids = read_ids()
    prog = read_json(STATE / "list_progress.json", {})
    have = {p.stem for p in PREC_DIR.glob("*.json")} if PREC_DIR.exists() else set()
    print(f"OC: {OC or '(미설정)'} · 오늘 사용 {used_today():,}/{DAILY_LIMIT:,}")
    if prog.get("total_pages"):
        print(f"목록: {prog.get('last_page', 0):,}/{prog['total_pages']:,} 페이지")
    print(f"민사 판례 ID: {len(ids):,}건")
    by_src: dict[str, int] = {}
    for m in ids.values():
        k = m.get("데이터출처명") or "(없음)"
        by_src[k] = by_src.get(k, 0) + 1
    for k, v in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"   - {k}: {v:,}")
    print(f"이 PC에 저장된 판례 본문: {len(have):,}건")
    for m in range(1, MEMBERS + 1):
        mine = [p for p in ids if p.isdigit() and int(p) % MEMBERS == m - 1]
        got = sum(1 for p in mine if p in have)
        print(f"   팀원 {m}: {got:,}/{len(mine):,}")
    laws = list(LAW_DIR.glob("*.json")) if LAW_DIR.exists() else []
    print(f"법령: {len(laws)}개")


# ───────────────────────── main ─────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="open.law.go.kr 민사 판례·법령 분담 수집기")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="민사 판례 ID 목록 수집 (data/civil_ids.jsonl)")
    ls.add_argument("--max-pages", type=int, default=0, help="이번 실행 최대 페이지 수 (테스트용)")

    f = sub.add_parser("fetch", help="내 담당 판례 본문 수집")
    f.add_argument("--member", type=int, required=True, help="내 번호 (1, 2, 3 ...)")
    f.add_argument("--members", type=int, default=MEMBERS, help=f"전체 인원 (기본 {MEMBERS})")
    f.add_argument("--source", default=None, help='데이터출처명 필터, 예: "대법원"')
    f.add_argument("--limit", type=int, default=0, help="이번 실행 최대 건수 (테스트용)")

    l = sub.add_parser("laws", help="민법 등 법령 본문 수집")
    l.add_argument("names", nargs="*", help="법령명 (생략 시 기본 민사 법령 목록)")

    sub.add_parser("status", help="진행 상황 보기")

    args = p.parse_args()
    if args.cmd != "status" and not OC:
        raise SystemExit(".env 에 LAW_OC=본인OC 를 넣어주세요. (.env.example 참고)")
    STATE.mkdir(parents=True, exist_ok=True)
    {"list": cmd_list, "fetch": cmd_fetch, "laws": cmd_laws, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
