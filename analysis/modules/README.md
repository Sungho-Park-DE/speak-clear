# analysis/modules

Let It Slop 모듈 폴더예요. 여기 바로 아래 폴더 하나가 독립적으로 갈아 끼울 수 있는 모듈 하나예요(이름은 `<name>_v<N>`, 예: `pitch_v2`). 모듈끼리는 공개 진입점(`__init__.py`)을 통해서도 서로 import하지 않고, `analysis/syncs`에서만 만나요. 요구 사항이 크게 바뀌면 기존 모듈을 고치지 말고 `slop-module` 스킬로 새 버전을 만들어요. 자세한 규칙은 `.claude/rules/let-it-slop.md`에 있고, import 경계는 `.claude/hooks/boundary_check.py`가 편집할 때마다 확인해요.
