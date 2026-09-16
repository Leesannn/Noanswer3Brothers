import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics.models import CanonicalSport
from analytics.services.normalizers import normalize_region, normalize_sport
from substitutes.models import Application, CenterContact, PhoneIdentity, Posting, ReputationRecord
from substitutes.services.phone import hash_phone, mask_phone


SEED = 2026

DEMO_CENTERS = [
    # (기관명, 지역, 담당자 휴대폰)
    ('데모-해담센터', '서울', '010-2000-0001'),
    ('데모-그린짐 성남점', '경기', '010-2000-0002'),
    ('데모-동아리 유소년축구클럽', '서울', '010-2000-0003'),
    ('데모-부산해운대수영장', '부산', '010-2000-0004'),
    ('데모-대전요가스튜디오', '대전', '010-2000-0005'),
]

# (center_index, 종목, 근무일 오프셋(일), 시작, 종료, 주소, 필요자격증, 시급, 단위, 모집인원, 설명, 상태)
DEMO_POSTINGS = [
    (0, '수영', 5, '10:00', '12:00', '서울 강남구 대치동', ['생활스포츠지도사 2급'], 32000, Posting.PayUnit.HOUR, 1,
     '담당 강사 개인 사정으로 유아 수영강습 1타임 대체 지도자가 필요합니다.', Posting.Status.RECRUITING),
    (1, '필라테스', 7, '07:00', '09:00', '경기 성남시 분당구', ['생활스포츠지도사 2급'], 40000, Posting.PayUnit.HOUR, 1,
     '오전반 필라테스 대타 강사를 구합니다.', Posting.Status.RECRUITING),
    (2, '축구', 1, '14:00', '16:00', '서울 마포구', ['유소년스포츠지도사'], 28000, Posting.PayUnit.HOUR, 2,
     '주말 유소년 축구클럽 대타 지도자 2명이 필요합니다.', Posting.Status.CLOSED),
    (3, '수영', 10, '09:00', '11:00', '부산 해운대구', ['생활스포츠지도사 2급', '인명구조자격'], 35000, Posting.PayUnit.HOUR, 1,
     '성인 수영반 대타이며 인명구조자격 보유자만 가능합니다.', Posting.Status.RECRUITING),
    (4, '요가', 3, '19:00', '20:30', '대전 서구', [], 30000, Posting.PayUnit.SESSION, 1,
     '저녁 요가 클래스 대타이며 자격 제한은 없습니다.', Posting.Status.RECRUITING),
    (0, '필라테스', -4, '10:00', '11:00', '서울 강남구', ['생활스포츠지도사 1급'], 45000, Posting.PayUnit.HOUR, 1,
     '이미 진행이 끝난 대타 건입니다 (완료 상태 화면 확인용).', Posting.Status.COMPLETED),
    (1, '헬스', 14, '06:00', '08:00', '경기 성남시', [], 38000, Posting.PayUnit.HOUR, 1,
     '새벽 PT 대타 강사를 구합니다.', Posting.Status.RECRUITING),
    (3, '수영', 2, '15:00', '17:00', '부산 해운대구', ['생활스포츠지도사 2급'], 33000, Posting.PayUnit.HOUR, 1,
     '청소년 수영강습 대타 강사가 필요합니다.', Posting.Status.RECRUITING),
]

# 신청자로 쓸 데모 강사 전화번호와 평판 프로필
# (휴대폰, 총 수행, 노쇼, 컴플레인, 긍정, 최근 6개월 이내 건수, 6개월~1년 건수, 1년 이상 건수)
DEMO_INSTRUCTORS = {
    'veteran_good': ('010-3000-1001', 15, 1, 0, 12, 8, 4, 3),
    'veteran_excellent': ('010-3000-1002', 41, 0, 0, 38, 25, 10, 6),
    'new_activity': ('010-3000-1003', 2, 0, 0, 1, 2, 0, 0),
    'risky': ('010-3000-1004', 5, 2, 1, 1, 5, 0, 0),
    'no_history': ('010-3000-1005', 0, 0, 0, 0, 0, 0, 0),
}

# 공고 인덱스(0-based, DEMO_POSTINGS 순서) -> 신청할 데모 강사 프로필 목록
DEMO_APPLICATIONS = {
    0: ['veteran_good', 'new_activity', 'no_history'],
    1: ['veteran_excellent'],
    3: ['risky'],
}


def _day(offset):
    return timezone.localdate() + timedelta(days=offset)


class Command(BaseCommand):
    help = '단기 대타 구하기 기능을 실험해볼 수 있도록 더미 공고·신청·평판 데이터를 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh', action='store_true',
            help='기존 더미 데이터를 먼저 삭제하고 다시 생성합니다.',
        )

    def handle(self, *args, **options):
        center_names = [name for name, _, _ in DEMO_CENTERS]
        instructor_hashes = [hash_phone(phone) for phone, *_ in DEMO_INSTRUCTORS.values()]

        already_exists = CenterContact.objects.filter(institution_name__in=center_names).exists()
        if already_exists and not options['refresh']:
            self.stdout.write('더미 데이터가 이미 존재합니다. 다시 생성하려면 --refresh 옵션을 사용하세요.')
            return

        if already_exists:
            ReputationRecord.objects.filter(phone_identity__phone_hash__in=instructor_hashes).delete()
            Application.objects.filter(posting__manager__institution_name__in=center_names).delete()
            Posting.objects.filter(manager__institution_name__in=center_names).delete()
            CenterContact.objects.filter(institution_name__in=center_names).delete()
            PhoneIdentity.objects.filter(phone_hash__in=instructor_hashes).delete()
            self.stdout.write('기존 더미 데이터를 삭제했습니다.')

        rng = random.Random(SEED)

        managers = []
        for institution_name, region, phone in DEMO_CENTERS:
            manager = CenterContact.objects.create(
                phone_hash=hash_phone(phone), phone_masked=mask_phone(phone),
                institution_name=institution_name, verified_at=timezone.now(),
            )
            managers.append(manager)

        sport_cache = {}

        def get_sport(name):
            if name not in sport_cache:
                normalized = normalize_sport(name)
                sport_cache[name], _ = CanonicalSport.objects.get_or_create(
                    normalized_name=normalized, defaults={'name': name, 'is_active': True},
                )
            return sport_cache[name]

        postings = []
        for (center_index, sport_name, day_offset, start, end, address, certs,
             pay, pay_unit, headcount, description, status) in DEMO_POSTINGS:
            region = address.split(' ')[0]
            posting = Posting.objects.create(
                manager=managers[center_index], sport=get_sport(sport_name),
                work_date=_day(day_offset), start_time=start, end_time=end,
                region=region, normalized_region=normalize_region(region), address=address,
                required_certifications=certs, pay_amount=pay, pay_unit=pay_unit,
                headcount=headcount, description=description, status=status,
            )
            postings.append(posting)

        phone_identities = {}
        for key, (phone, *_rest) in DEMO_INSTRUCTORS.items():
            phone_hash = hash_phone(phone)
            phone_identities[key], _ = PhoneIdentity.objects.get_or_create(
                phone_hash=phone_hash, defaults={'phone_masked': mask_phone(phone)},
            )

        management_links = []
        for posting_index, profile_keys in DEMO_APPLICATIONS.items():
            posting = postings[posting_index]
            for key in profile_keys:
                phone, total, no_show, complaint, positive, recent, mid, old = DEMO_INSTRUCTORS[key]
                identity = phone_identities[key]
                Application.objects.get_or_create(
                    posting=posting, phone_identity=identity,
                    defaults={'phone_masked': identity.phone_masked, 'certification_verified': True},
                )
                self._seed_reputation(rng, identity, posting.manager, total, no_show, complaint, positive, recent, mid, old)
            management_links.append(posting)

        self.stdout.write(self.style.SUCCESS(
            f'센터 {len(managers)}곳, 공고 {len(postings)}건, 신청/평판 데이터를 생성했습니다.'
        ))
        self.stdout.write('신청자가 있는 공고의 관리 링크 (센터용 신청자 관리 화면):')
        from substitutes.services.tokens import generate_management_token
        for posting in management_links:
            token = generate_management_token(posting.pk)
            self.stdout.write(f'  /substitutes/postings/{posting.pk}/manage/{token}/  ({posting})')

    def _seed_reputation(self, rng, identity, manager, total, no_show, complaint, positive, recent, mid, old):
        if total == 0:
            return
        days_ago = (
            [rng.randint(1, 181) for _ in range(recent)]
            + [rng.randint(182, 364) for _ in range(mid)]
            + [rng.randint(365, 720) for _ in range(old)]
        )
        rng.shuffle(days_ago)
        flags = (
            [('no_show', True)] * no_show
            + [('complaint', True)] * complaint
            + [('positive', True)] * positive
            + [('neutral', True)] * max(0, total - no_show - complaint - positive)
        )
        rng.shuffle(flags)

        records = []
        for days, (kind, _) in zip(days_ago, flags):
            records.append(ReputationRecord(
                phone_identity=identity,
                posting=None,
                is_no_show=(kind == 'no_show'),
                is_complaint=(kind == 'complaint'),
                positive_tags=(['성실함', '시간엄수'] if kind == 'positive' else []),
                comment='' if kind == 'neutral' else f'데모 데이터: {kind}',
                occurred_at=timezone.now() - timedelta(days=days),
                created_by=manager,
            ))
        ReputationRecord.objects.bulk_create(records)
