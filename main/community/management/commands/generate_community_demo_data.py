from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.utils import timezone

from community.models import Comment, Post


TITLE_PREFIX = '[데모]'
DEMO_PASSWORD = 'demo1234'

# (카테고리, 제목, 닉네임, 내용, 조회수, 며칠 전, 공지여부, 댓글 목록[(닉네임, 내용, 시간전(분))])
DEMO_POSTS = [
    (
        Post.Category.FREE, f'{TITLE_PREFIX} 커뮤니티 이용 안내',
        '운영자',
        '안녕하세요! 시험정보, 기출문제, 자격증 관련 궁금증을 자유롭게 나누는 익명 게시판입니다.\n'
        '글 작성 시 입력한 비밀번호로만 본인 글을 수정·삭제할 수 있으니 잊지 말고 기억해두세요.',
        312, 20, True, [],
    ),
    (
        Post.Category.FREE, f'{TITLE_PREFIX} 다들 대타 뛰어보신 분 계신가요?',
        '물속탐험가',
        '단기 대타 구하기 게시판으로 처음 신청해봤는데 생각보다 절차가 간단하네요. 다른 분들 후기도 궁금합니다.',
        58, 2, False,
        [('헬스누나', '저도 지난주에 처음 해봤어요! 이름·연락처·비밀번호만 입력하면 되니까 편하더라고요.', 90)],
    ),
    (
        Post.Category.EXAM_INFO, f'{TITLE_PREFIX} 2026년 상반기 생활스포츠지도사 2급 접수 후기',
        '수영강사김쌤',
        '접수 첫날 오전에 신청했는데 큰 지연 없이 처리됐습니다. 사진 규격만 미리 맞춰가면 수월해요.\n'
        '실기 응시장은 각자 배정되는 지역 체육시설이니 미리 위치 확인해두시는 걸 추천합니다.',
        204, 6, False,
        [
            ('예비지도자', '정보 감사합니다! 사진 규격이 정확히 어떻게 되나요?', 1200),
            ('수영강사김쌤', '3.5x4.5cm 반명함판 기준이었어요. 국민체육진흥공단 공고문에 정확히 나와있습니다.', 600),
        ],
    ),
    (
        Post.Category.EXAM_INFO, f'{TITLE_PREFIX} 유소년스포츠지도사 실기시험장 후기 (부산)',
        '부산코치',
        '해운대 소재 체육시설에서 실기 봤는데 대기시간이 꽤 길었습니다. 여유있게 도착하시길 추천드려요.',
        87, 12, False, [],
    ),
    (
        Post.Category.MATERIALS, f'{TITLE_PREFIX} 2025년 생활스포츠지도사 필기 기출문제 정리 공유합니다',
        '기출정리러',
        '작년에 정리해둔 필기 기출 요약본입니다. 스포츠사회학·교육학 파트 위주로 정리했어요.\n'
        '틀린 부분 있으면 댓글로 알려주시면 반영하겠습니다.',
        421, 30, False,
        [('감사합니다', '덕분에 시험 준비 수월했습니다! 감사해요.', 4000)],
    ),
    (
        Post.Category.MATERIALS, f'{TITLE_PREFIX} 수영 실기시험 체크리스트 정리',
        '수영강사김쌤',
        '자유형/배영/평영/접영 순서별로 감점 포인트 정리했습니다. 실기 준비하시는 분들 참고하세요.',
        156, 15, False, [],
    ),
    (
        Post.Category.QNA, f'{TITLE_PREFIX} 2급이랑 1급 차이가 실무에서 크게 나나요?',
        '고민중인예비강사',
        '2급 취득 후 바로 1급 준비할지, 실무 경험 먼저 쌓을지 고민입니다. 선배님들 의견 부탁드려요.',
        133, 4, False,
        [
            ('현직트레이너', '기관 채용 볼 때는 1급이 확실히 유리해요. 시간 되시면 바로 준비하시는 것도 나쁘지 않습니다.', 2000),
        ],
    ),
    (
        Post.Category.QNA, f'{TITLE_PREFIX} 인명구조자격 갱신 주기 아시는 분?',
        '해운대라이프가드',
        '인명구조자격 갱신 주기랑 갱신 교육 신청 방법 아시는 분 계신가요?',
        41, 1, False, [],
    ),
]


class Command(BaseCommand):
    help = '커뮤니티 게시판을 실험해볼 수 있도록 더미 게시글·댓글 데이터를 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh', action='store_true',
            help='기존 더미 데이터를 먼저 삭제하고 다시 생성합니다.',
        )

    def handle(self, *args, **options):
        already_exists = Post.objects.filter(title__startswith=TITLE_PREFIX).exists()
        if already_exists and not options['refresh']:
            self.stdout.write('더미 데이터가 이미 존재합니다. 다시 생성하려면 --refresh 옵션을 사용하세요.')
            return

        if already_exists:
            deleted, _ = Post.objects.filter(title__startswith=TITLE_PREFIX).delete()
            self.stdout.write(f'기존 더미 게시글 {deleted}건을 삭제했습니다.')

        password_hash = make_password(DEMO_PASSWORD)
        now = timezone.now()
        created_posts = 0
        created_comments = 0

        for category, title, nickname, content, view_count, days_ago, is_notice, comments in DEMO_POSTS:
            post = Post.objects.create(
                category=category, title=title, nickname=nickname,
                password_hash=password_hash, content=content,
                view_count=view_count, is_notice=is_notice,
            )
            Post.objects.filter(pk=post.pk).update(created_at=now - timedelta(days=days_ago))
            created_posts += 1

            for comment_nickname, comment_content, minutes_ago in comments:
                comment = Comment.objects.create(
                    post=post, nickname=comment_nickname, content=comment_content,
                    password_hash=password_hash,
                )
                Comment.objects.filter(pk=comment.pk).update(created_at=now - timedelta(minutes=minutes_ago))
                created_comments += 1

        self.stdout.write(self.style.SUCCESS(
            f'더미 게시글 {created_posts}건, 댓글 {created_comments}건을 생성했습니다. '
            f'(모든 더미 글의 비밀번호는 "{DEMO_PASSWORD}" 입니다)'
        ))
