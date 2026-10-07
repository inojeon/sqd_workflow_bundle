"""guide.md와 실제 run_steps.py에서 외부 자산 없는 HTML 가이드를 생성합니다."""
from html import escape
from pathlib import Path

import markdown


def main():
    root = Path(__file__).resolve().parents[1]
    body = markdown.markdown(
        (root / "docs/guide.md").read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "toc"],
        extension_configs={"toc": {"title": "이 문서의 내용", "toc_depth": "2-3"}},
    )
    # 모바일에서는 표 내부에서만 가로 스크롤하도록 제한합니다.
    body = body.replace("<table>", '<div class="table-wrap"><table>')
    body = body.replace("</table>", "</table></div>")
    source = escape((root / "run_steps.py").read_text(encoding="utf-8"))
    css = (root / "tools/guide.css").read_text(encoding="utf-8")
    page = f'''<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SQD 워크플로우 실행 가이드 — run_steps.py</title><style>{css}</style></head>
<body><header><span>IBM SQD · WORKFLOW HANDOFF</span>
<nav aria-label="문서 바로가기"><a href="../README.md">빠른 시작</a>
<a href="guide.md">Markdown 원본</a><a href="../validation/README.md">검증 기록</a>
<a href="#source-code">실행 코드 전체</a></nav></header>
<main>{body}
<section id="source-code"><h2>부록. run_steps.py 전체 코드</h2>
<p>문서를 생성할 때 실제 파일에서 읽은 코드입니다. <a href="../run_steps.py">원본 파일 열기</a></p>
<pre><code>{source}</code></pre></section></main>
<footer>독립 실행 패키지 · SDK 연결 전 단계 · 브라우저 인쇄로 PDF 저장 가능</footer>
</body></html>'''
    output = root / "docs/guide.html"
    output.write_text(page, encoding="utf-8")
    print(f"Generated {output}")


if __name__ == "__main__":
    main()
