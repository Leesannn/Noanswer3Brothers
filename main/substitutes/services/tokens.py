"""센터 담당자가 로그인 없이 신청자 관리 화면에 재접속하기 위한 서명 링크.

posting.id를 서버 SECRET_KEY로 서명해 위조·추측이 불가능한 토큰을 만든다.
DB에 별도로 저장하지 않는 상태(stateless) 방식이라 토큰 자체가 곧 접근
권한이며, 공고 담당자에게 발급된 링크를 아는 사람만 관리 화면에 들어갈 수
있다.
"""
from django.core import signing


SALT = 'substitutes.posting.manage'


def generate_management_token(posting_id):
    return signing.dumps(posting_id, salt=SALT)


def verify_management_token(token):
    try:
        return signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None
