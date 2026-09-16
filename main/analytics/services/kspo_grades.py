"""국민체육진흥공단 체육지도자 자격검정 사이트(sqms.kspo.or.kr)의 자격등급 코드.

연간일정계획(schedPlan.kspo?QF_GRADE_CD=...)과 자격제도안내
(licenseInfo{Code}.kspo)에서 공통으로 쓰는 9개 등급 코드다.
"""

GRADES = [
    ('PSC1', '1급 전문스포츠지도사'),
    ('PSC2', '2급 전문스포츠지도사'),
    ('LSC1', '1급 생활스포츠지도사'),
    ('LSC2', '2급 생활스포츠지도사'),
    ('HEXM', '건강운동관리사'),
    ('YUSC', '유소년스포츠지도사'),
    ('OLSC', '노인스포츠지도사'),
    ('DSC1', '1급 장애인스포츠지도사'),
    ('DSC2', '2급 장애인스포츠지도사'),
]

GRADE_NAMES = dict(GRADES)
GRADE_CODES = [code for code, _ in GRADES]


def license_info_url(grade_code):
    # 코드를 타이틀케이스로 바꾼 형태가 URL에 쓰인다 (예: PSC1 -> Psc1, HEXM -> Hexm).
    return f'https://sqms.kspo.or.kr/info/licenseInfo{grade_code.capitalize()}.kspo'


def schedule_url(grade_code):
    return f'https://sqms.kspo.or.kr/info/schedPlan.kspo?QF_GRADE_CD={grade_code}'
