"""자격증 보유 여부 조회 연동 지점.

실제 서비스에서는 회원·자격증 DB에서 phone_hash로 강사를 찾아 공고가
요구하는 자격증 목록과 대조해야 한다. 지금은 실제 연동 전이므로 항상
보유한 것으로 취급하는 모의(mock) 구현이며, 테스트를 위해 특정 전화번호
해시를 차단 목록에 넣어 거부 케이스를 재현할 수 있다.
"""

_BLOCKED_PHONE_HASHES = set()


def has_required_certification(phone_hash, required_certifications):
    if not required_certifications:
        return True
    return phone_hash not in _BLOCKED_PHONE_HASHES
