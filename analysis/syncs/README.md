# analysis/syncs

모듈이 만나는 유일한 곳(sync·gate 계층)이에요. gate 함수 하나가 기능 플래그로 모듈 버전을 고르고, 플래그 기본값은 꺼짐이라 끄면 지금 동작이 그대로 유지돼요. 플래그는 `flags.py`의 `is_enabled("pitch_v2")`로 확인하고, 이 함수는 쉼표로 구분한 환경 변수 `VP_FLAGS`를 읽어요(첫 gate를 만들 때 함께 만들어요). 모듈은 서로를 import하지 않고 여기서만 조합돼요.
