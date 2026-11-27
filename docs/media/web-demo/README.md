# v6r2 웹 시연 영상 (`../v6r2-web-demo.mp4`) 다시 만들기

- 왼쪽: dev 브랜치 `app/web` 화면을 그대로 띄우고, API 응답(`/api/config`, `/api/chat`, `/api/doc`)만 `mock.json` 으로 대신한다.
- 오른쪽: `composite.html` — 확신도·파이프라인·중간 데이터를 웹 화면 조작과 같은 시간축으로 재생.
- 값의 출처: 검색·연결·점수는 실측/코드 계산, 1차 판단은 v6r 3회 실측, 지문 ㄷ 2차 판단(참 0.95)은 v6r2 실측 전 예시.

```
mkdir -p /tmp/web && git archive origin/dev app/web | tar -x -C /tmp/web
cp docs/media/web-demo/composite.html docs/media/web-demo/mock.json /tmp/web/
node docs/media/web-demo/record.js /tmp/web /tmp/out          # webm 녹화 (약 90초)
ffmpeg -ss 1.2 -i /tmp/out/*.webm -c:v libx264 -pix_fmt yuv420p -crf 24 -r 30 docs/media/v6r2-web-demo.mp4
```
