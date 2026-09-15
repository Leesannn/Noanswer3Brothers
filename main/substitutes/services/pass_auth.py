"""PASS 본인인증 연동 지점.

실제 서비스에서는 브라우저가 PASS 인증사(이통 3사 PASS, 나이스평가정보 등)
SDK로 인증을 마친 뒤 돌려주는 인증 토큰을 이 함수에서 인증사 서버에 검증
요청하고, 그 응답의 name/phone/CI 값으로 PassIdentity를 구성해야 한다.

지금은 실제 연동 전이므로, 신청자가 입력한 이름·전화번호를 인증된 값으로
그대로 취급하는 모의(mock) 구현이다. 실제 연동 시 이 함수의 시그니처만
유지한 채 내부 구현을 교체하면 호출부(views.py)는 수정할 필요가 없다.
"""
from dataclasses import dataclass


@dataclass
class PassIdentity:
    name: str
    phone: str  # 원문 전화번호. 호출자는 해시로 변환한 뒤 즉시 버려야 한다.
    ci_hash: str = ''


def verify_pass_result(name, phone):
    name = (name or '').strip()
    phone = (phone or '').strip()
    if not name or not phone:
        return None
    return PassIdentity(name=name, phone=phone)
